"""
Django management command to run the Nebulous Discord bot
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
import ssl
import certifi
import aiohttp
from datetime import datetime, timezone
from typing import Optional
from django.core.management.base import BaseCommand

from nebulous_bot.config import Config, harness_command_allowed
from nebulous_bot.server_monitor import ServerMonitor
from nebulous_bot.server_formatter import ServerFormatter
from nebulous_bot.command_logging import setup_command_metrics
from nebulous_bot.help_command import NebulousHelpCommand
from nebulous_bot.retention import run_retention_loop
from nebulous_bot.cogs.setup import SetupCog
from nebulous_bot.cogs.stats import StatsCog
from nebulous_bot.cogs.servers import ServersCog
from nebulous_bot.cogs.admin import AdminCog
from nebulous_bot.cogs.nextgame import NextGameCog
from nebulous_bot.cogs.advice import AdviceCog
from nebulous_bot.cogs.fleet_strategy import FleetStrategyCog

# DELIBERATELY EAGER: cogs.formation imports formation_optimizer (numpy +
# matplotlib, ~100+ MiB RSS) at module scope, so importing it HERE — at
# module scope, before the event loop exists — keeps that cost at boot.
# Do NOT move this into run_bot()/add_cog time or make it lazy: v2.3.4
# tried exactly that, and the deferred import ran for minutes on the
# 1/8-OCPU VM at first !graph/!formation, starving the event loop
# (blocked heartbeats, gateway resets, every command hung).
from nebulous_bot.cogs.formation import FormationCog

logger = logging.getLogger("nebulous_bot")

GLOBAL_SYNC_CONFIRMATION = "CONFIRM_GLOBAL_COMMAND_SYNC"


class CommandSyncInputError(ValueError):
    """Raised when a manual command-tree sync request is not safely scoped."""


def create_ssl_context():
    """Create SSL context for Discord connections"""
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return ssl_context


def create_bot(*, message_content: Optional[bool] = None) -> commands.Bot:
    """Construct the bot without connecting to Discord.

    Message Content deliberately remains enabled for the compatibility release.
    Keeping construction separate from ``handle`` lets tests inspect the runtime
    contract without opening a gateway connection.
    """
    intents = discord.Intents.default()
    intents.message_content = Config.DISCORD_MESSAGE_CONTENT if message_content is None else message_content

    bot = commands.Bot(
        command_prefix=commands.when_mentioned_or(Config.COMMAND_PREFIX),
        intents=intents,
        help_command=NebulousHelpCommand(),
    )
    setup_command_metrics(bot)

    # Shared runtime state the cogs read via the bot object. These stay None
    # until on_ready fills them in.
    bot.server_monitor = None
    bot.formatter = None
    bot.deployment_time = None

    register_sync_command(bot)
    register_application_command_error_handler(bot)
    return bot


async def sync_application_commands(
    bot: commands.Bot,
    *,
    scope: str,
    target: str,
) -> tuple[list[app_commands.AppCommand], str]:
    """Perform one explicitly scoped command-tree sync.

    Guild syncs are restricted to the configured test-guild allowlist. Global
    syncs require a conspicuous confirmation phrase. Nothing calls this helper
    automatically; it is exposed only by the owner-only prefix command below.
    """
    normalized_scope = scope.casefold()
    if normalized_scope == "guild":
        try:
            guild_id = int(target)
        except (TypeError, ValueError) as exc:
            raise CommandSyncInputError("The test guild ID must be an integer.") from exc

        if guild_id not in Config.TEST_COMMAND_GUILD_IDS:
            raise CommandSyncInputError(
                "That guild is not in TEST_COMMAND_GUILD_IDS; refusing to sync it."
            )

        guild = discord.Object(id=guild_id)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        return synced, f"test guild {guild_id}"

    if normalized_scope == "global":
        if target != GLOBAL_SYNC_CONFIRMATION:
            raise CommandSyncInputError(
                f"Global sync requires the exact confirmation token {GLOBAL_SYNC_CONFIRMATION}."
            )
        synced = await bot.tree.sync()
        return synced, "GLOBAL application-command scope"

    raise CommandSyncInputError("Scope must be `guild` or `global`.")


def register_sync_command(bot: commands.Bot) -> None:
    """Register the hidden, prefix-only owner operation for deliberate syncs."""

    @bot.command(name="synccommands", hidden=True)
    @commands.is_owner()
    async def synccommands(ctx: commands.Context, scope: str, target: str):
        """Sync app commands: guild <test-guild-id> or global <confirmation>."""
        try:
            synced, destination = await sync_application_commands(
                bot,
                scope=scope,
                target=target,
            )
        except CommandSyncInputError as exc:
            await ctx.send(f"❌ {exc}")
            return

        await ctx.send(f"✅ Synchronized {len(synced)} application commands to {destination}.")


async def send_application_error(interaction: discord.Interaction, message: str) -> None:
    """Send a bounded ephemeral error whether or not the interaction was deferred."""
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def handle_application_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """Return safe, user-actionable errors for slash-command failures."""
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ This command is on cooldown — try again in {error.retry_after:.0f}s."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.CheckFailure):
        message = "❌ You can't use this command here."
    elif isinstance(error, (app_commands.TransformerError, app_commands.CommandSignatureMismatch)):
        message = "❌ Invalid command options. Reopen the command picker and try again."
    else:
        command_name = interaction.command.qualified_name if interaction.command else "unknown"
        logger.error("Application command error in %s: %s", command_name, error, exc_info=error)
        message = "❌ Something went wrong running that command. The error has been logged."

    await send_application_error(interaction, message)


def register_application_command_error_handler(bot: commands.Bot) -> None:
    """Install the application-command error handler on this bot's tree."""
    bot.tree.error(handle_application_command_error)


async def handle_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """Handle prefix and hybrid-command errors without leaking slash failures."""
    if getattr(error, 'fleet_strategy_handled', False):
        return
    if isinstance(error, commands.CommandNotFound):
        return

    response_options = {"ephemeral": True} if ctx.interaction is not None else {}
    command_name = ctx.command.qualified_name if ctx.command else "command"
    clean_prefix = getattr(ctx, "clean_prefix", Config.COMMAND_PREFIX)

    if isinstance(error, commands.CommandOnCooldown):
        label = f"/{command_name}" if ctx.interaction is not None else f"{clean_prefix}{command_name}"
        await ctx.send(
            f"⏳ `{label}` is on cooldown — try again in {error.retry_after:.0f}s. "
            "(Recent results keep updating in place.)",
            **response_options,
        )
        return

    if isinstance(error, (commands.NotOwner, commands.MissingPermissions)):
        await ctx.send("❌ You don't have permission to use this command.", **response_options)
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ This command only works in a server, not in DMs.", **response_options)
        return

    wrapped_app_error = (
        error.original if isinstance(error, commands.HybridCommandError) else None
    )
    if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)) or isinstance(
        wrapped_app_error, app_commands.TransformerError
    ):
        if ctx.interaction is not None:
            message = "❌ Invalid command options. Reopen the command picker and try again."
        else:
            message = f"❌ Invalid usage. See `{clean_prefix}help {command_name}` for examples."
        await ctx.send(message, **response_options)
        return

    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You can't use this command here.", **response_options)
        return

    logger.error("Command error in %s: %s", ctx.command, error, exc_info=error)
    embed = discord.Embed(
        title="❌ Command Error",
        description="Something went wrong running that command. The error has been logged.",
        color=Config.EMBED_COLOR_NO_SERVERS,
    )
    await ctx.send(embed=embed, **response_options)


class Command(BaseCommand):
    help = "Runs the Nebulous Discord bot"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-auto-start",
            action="store_true",
            help="Do not automatically start monitoring",
        )
        parser.add_argument(
            "--without-message-content",
            action="store_true",
            help="Disable Message Content, overriding DISCORD_MESSAGE_CONTENT.",
        )

    def handle(self, *args, **options):
        """Main command handler"""
        self.stdout.write(self.style.SUCCESS("Starting Nebulous Discord Bot..."))

        # Set up bot without connecting or synchronizing its command tree.
        bot = create_bot(message_content=False if options["without_message_content"] else None)
        logger.info("Message Content intent requested: %s", bot.intents.message_content)

        # Global variables
        server_monitor = None
        formatter = None
        ssl_context = None
        connector = None
        deployment_time: Optional[datetime] = None
        retention_task: Optional[asyncio.Task] = None

        @bot.event
        async def on_message(message):
            """Default command routing, plus the test-harness allowlist.

            discord.py's process_commands drops every bot-authored message,
            which is correct in production. The test harness (see
            docs/DISCORD_TEST_HARNESS.md) bypasses that for an allowlisted
            puppet bot in the designated test guild only — both lists
            empty by default, fail closed (config.harness_command_allowed);
            get_context/invoke is the documented way around the author.bot
            check. Never our own messages, loop-safe by id.
            """
            if message.author.bot:
                if harness_command_allowed(
                        message.author.id,
                        message.guild.id if message.guild else None,
                        bot.user.id,
                        Config.TEST_COMMAND_BOT_IDS,
                        Config.TEST_COMMAND_GUILD_IDS):
                    ctx = await bot.get_context(message)
                    await bot.invoke(ctx)
                return
            await bot.process_commands(message)

        @bot.event
        async def on_ready():
            """Called when the bot is ready"""
            nonlocal server_monitor, formatter, deployment_time, retention_task

            logger.info(f"{bot.user} has connected to Discord!")
            logger.info(f"Bot is in {len(bot.guilds)} guilds")
            self.stdout.write(self.style.SUCCESS(f"✅ Bot connected as {bot.user}"))

            # Track deployment time on first connection (if not already set)
            if deployment_time is None:
                deployment_time = datetime.now(timezone.utc)
            bot.deployment_time = deployment_time

            # Validate configuration
            try:
                Config.validate()
                logger.info("Configuration validated successfully")
            except ValueError as e:
                logger.error(f"Configuration error: {e}")
                self.stdout.write(self.style.ERROR(f"❌ Configuration error: {e}"))
                await bot.close()
                return

            # Initialize server monitor if not already initialized
            if server_monitor is None:
                logger.info("Initializing server monitor for the first time")
                server_monitor = ServerMonitor(bot)
                formatter = ServerFormatter()
                server_monitor.set_formatter(formatter)
            else:
                logger.info("Bot reconnected - server monitor already initialized")
            bot.server_monitor = server_monitor
            bot.formatter = formatter

            # Always ensure monitoring is running (restart if it stopped)
            if not options["no_auto_start"]:
                monitoring_running = server_monitor.monitoring_task and not server_monitor.monitoring_task.done()
                if not monitoring_running:
                    logger.info("Starting/restarting monitoring loop")
                    await server_monitor.start_monitoring()
                    self.stdout.write(self.style.SUCCESS("✅ Server monitoring started"))
                else:
                    logger.info("Monitoring loop already running")

            # Daily purge of legacy command text older than 30 days
            # (PRIVACY.md retention commitment). New rows leave that column
            # empty. on_ready refires on
            # reconnect, so only start the task if it isn't running.
            if retention_task is None or retention_task.done():
                retention_task = asyncio.create_task(run_retention_loop())

            # Set bot activity
            activity = discord.Activity(type=discord.ActivityType.watching, name=f"{Config.GAME_NAME} servers")
            await bot.change_presence(activity=activity)

        # Removed on_disconnect handler - the health check will auto-restart monitoring if needed
        # Stopping monitoring on disconnect was causing issues with reconnections

        @bot.event
        async def on_guild_join(guild):
            """Welcome a new guild with setup instructions."""
            logger.info(f"Joined guild '{guild.name}' (id={guild.id})")

            target = guild.system_channel
            if not target or not target.permissions_for(guild.me).send_messages:
                target = next(
                    (ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages),
                    None,
                )
            if target is None:
                logger.info(f"No writable channel in '{guild.name}'; skipping welcome message")
                return

            embed = discord.Embed(
                title=f"👋 Thanks for adding me to {guild.name}!",
                description=(
                    f"I monitor live server activity for **{Config.GAME_NAME}**.\n\n"
                    "**To finish setup**, an admin should pick where the live status embed lives:\n"
                    "Use `/setstatuschannel` and select a channel, or run it without an option "
                    "in the channel you want me to use.\n\n"
                    "Other commands work in any channel right away: `/listservers`, `/openlobbies`, "
                    "`/stats`, `/nextgame`, `/graph`, and `/formation`. Discord's command picker "
                    "shows the complete menu."
                ),
                color=Config.EMBED_COLOR,
            )
            try:
                await target.send(embed=embed)
            except Exception as e:
                logger.warning(f"Could not post welcome message to '{guild.name}': {e}")

        @bot.event
        async def on_command_error(ctx, error):
            await handle_command_error(ctx, error)

        async def run_bot():
            """Main function to run the bot"""
            nonlocal ssl_context, connector

            try:
                # Create SSL connector inside the event loop
                ssl_context = create_ssl_context()
                connector = aiohttp.TCPConnector(ssl=ssl_context)

                # Set the connector for the bot's HTTP client
                bot.http.connector = connector

                # Register command cogs before connecting to the gateway.
                await bot.add_cog(SetupCog(bot))
                await bot.add_cog(StatsCog(bot))
                await bot.add_cog(ServersCog(bot))
                await bot.add_cog(AdminCog(bot))
                await bot.add_cog(FormationCog(bot))
                await bot.add_cog(NextGameCog(bot))
                await bot.add_cog(AdviceCog(bot))
                await bot.add_cog(FleetStrategyCog(bot))

                await bot.start(Config.DISCORD_TOKEN)
            except KeyboardInterrupt:
                logger.info("Bot shutdown requested")
                self.stdout.write(self.style.WARNING("Bot shutdown requested"))
            except Exception as e:
                logger.error(f"Bot error: {e}")
                self.stdout.write(self.style.ERROR(f"Bot error: {e}"))
            finally:
                await bot.close()
                if connector:
                    await connector.close()

        # Run the bot
        try:
            asyncio.run(run_bot())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nBot stopped by user"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to start bot: {e}"))
            raise

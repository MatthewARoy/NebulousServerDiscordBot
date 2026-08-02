"""
Django management command to run the Nebulous Discord bot
"""

import discord
from discord.ext import commands
import logging
import asyncio
import ssl
import certifi
import aiohttp
from datetime import datetime, timezone
from typing import Optional
from django.core.management.base import BaseCommand

from nebulous_bot.config import Config
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

# DELIBERATELY EAGER: cogs.formation imports formation_optimizer (numpy +
# matplotlib, ~100+ MiB RSS) at module scope, so importing it HERE — at
# module scope, before the event loop exists — keeps that cost at boot.
# Do NOT move this into run_bot()/add_cog time or make it lazy: v2.3.4
# tried exactly that, and the deferred import ran for minutes on the
# 1/8-OCPU VM at first !graph/!formation, starving the event loop
# (blocked heartbeats, gateway resets, every command hung).
from nebulous_bot.cogs.formation import FormationCog

logger = logging.getLogger("nebulous_bot")


def create_ssl_context():
    """Create SSL context for Discord connections"""
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return ssl_context


class Command(BaseCommand):
    help = "Runs the Nebulous Discord bot"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-auto-start",
            action="store_true",
            help="Do not automatically start monitoring",
        )

    def handle(self, *args, **options):
        """Main command handler"""
        self.stdout.write(self.style.SUCCESS("Starting Nebulous Discord Bot..."))

        # Set up bot
        intents = discord.Intents.default()
        intents.message_content = True

        bot = commands.Bot(
            command_prefix=Config.COMMAND_PREFIX,
            intents=intents,
            help_command=NebulousHelpCommand(),
        )
        setup_command_metrics(bot)

        # Shared runtime state the cogs read via the bot object. These stay
        # None until on_ready fills them in — cog commands must keep their
        # None-guards ("monitoring not initialized yet").
        bot.server_monitor = None
        bot.formatter = None
        bot.deployment_time = None

        # Global variables
        server_monitor = None
        formatter = None
        ssl_context = None
        connector = None
        deployment_time: Optional[datetime] = None
        retention_task: Optional[asyncio.Task] = None

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

            # Daily purge of stored message content older than 30 days
            # (PRIVACY.md retention commitment). on_ready refires on
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
                    "`!setstatuschannel #some-channel`\n"
                    "Or run `!setstatuschannel` (no argument) in the channel you want me to use.\n\n"
                    "Other commands work in any channel right away: `!listservers`, `!openlobbies`, "
                    "`!stats`, `!nextgame`, `!graph`, `!formation`. Run `!help` for the full command menu."
                ),
                color=Config.EMBED_COLOR,
            )
            try:
                await target.send(embed=embed)
            except Exception as e:
                logger.warning(f"Could not post welcome message to '{guild.name}': {e}")

        @bot.event
        async def on_command_error(ctx, error):
            """Handle command errors with user-friendly messages.

            Raw exception text is logged, never echoed to the channel.
            """
            if isinstance(error, commands.CommandNotFound):
                return  # Ignore unknown commands

            if isinstance(error, commands.CommandOnCooldown):
                await ctx.send(
                    f"⏳ `!{ctx.command}` is on cooldown — try again in {error.retry_after:.0f}s. "
                    "(Recent results keep updating in place.)"
                )
                return

            if isinstance(error, (commands.NotOwner, commands.MissingPermissions)):
                await ctx.send("❌ You don't have permission to use this command.")
                return

            if isinstance(error, commands.NoPrivateMessage):
                await ctx.send("❌ This command only works in a server, not in DMs.")
                return

            if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
                await ctx.send(f"❌ Invalid usage. See `!help {ctx.command.qualified_name}` for examples.")
                return

            if isinstance(error, commands.CheckFailure):
                await ctx.send("❌ You can't use this command here.")
                return

            logger.error(f"Command error in {ctx.command}: {error}", exc_info=error)
            embed = discord.Embed(
                title="❌ Command Error",
                description="Something went wrong running that command. The error has been logged.",
                color=Config.EMBED_COLOR_NO_SERVERS,
            )
            await ctx.send(embed=embed)

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

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
from nebulous_bot.cogs.setup import SetupCog
from nebulous_bot.cogs.stats import StatsCog
from nebulous_bot.cogs.servers import ServersCog
from nebulous_bot.cogs.admin import AdminCog

# DELIBERATELY EAGER: cogs.formation imports formation_optimizer (numpy +
# matplotlib, ~100+ MiB RSS) at module scope, so importing it HERE — at
# module scope, before the event loop exists — keeps that cost at boot.
# Do NOT move this into run_bot()/add_cog time or make it lazy: v2.3.4
# tried exactly that, and the deferred import ran for minutes on the
# 1/8-OCPU VM at first !graph/!formation, starving the event loop
# (blocked heartbeats, gateway resets, every command hung).
from nebulous_bot.cogs.formation import FormationCog

logger = logging.getLogger('nebulous_bot')


def create_ssl_context():
    """Create SSL context for Discord connections"""
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return ssl_context


class Command(BaseCommand):
    help = 'Runs the Nebulous Discord bot'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-auto-start',
            action='store_true',
            help='Do not automatically start monitoring',
        )

    def handle(self, *args, **options):
        """Main command handler"""
        self.stdout.write(self.style.SUCCESS('Starting Nebulous Discord Bot...'))
        
        # Set up bot
        intents = discord.Intents.default()
        intents.message_content = True
        
        bot = commands.Bot(
            command_prefix=Config.COMMAND_PREFIX, 
            intents=intents
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
        
        @bot.event
        async def on_ready():
            """Called when the bot is ready"""
            nonlocal server_monitor, formatter, deployment_time
            
            logger.info(f'{bot.user} has connected to Discord!')
            logger.info(f'Bot is in {len(bot.guilds)} guilds')
            self.stdout.write(self.style.SUCCESS(f'✅ Bot connected as {bot.user}'))
            
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
                self.stdout.write(self.style.ERROR(f'❌ Configuration error: {e}'))
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
            if not options['no_auto_start']:
                monitoring_running = server_monitor.monitoring_task and not server_monitor.monitoring_task.done()
                if not monitoring_running:
                    logger.info("Starting/restarting monitoring loop")
                    await server_monitor.start_monitoring()
                    self.stdout.write(self.style.SUCCESS('✅ Server monitoring started'))
                else:
                    logger.info("Monitoring loop already running")
            
            # Set bot activity
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{Config.GAME_NAME} servers"
            )
            await bot.change_presence(activity=activity)

        # Removed on_disconnect handler - the health check will auto-restart monitoring if needed
        # Stopping monitoring on disconnect was causing issues with reconnections

        @bot.command(name='nextgame', aliases=['notify', 'notifyme', 'ng'])
        @commands.cooldown(2, 30, commands.BucketType.user)
        async def next_game_notify(ctx, *, args: str = ""):
            """
            Get notified when the next game is ready to join.

            Usage: !nextgame [ptb] [modded] [newplayer] [lobby] [--skip]
            - !nextgame - Notify for all servers
            - !nextgame ptb - Notify only for PTB (test branch) servers
            - !nextgame modded - Notify only for servers running mods
            - !nextgame newplayer - Notify only for new-player servers
            - !nextgame lobby - Only notify when a lobby is ready (skip debrief alerts)
            - !nextgame --skip (or -skip) - Don't notify for lobbies already active right now

            You'll be pinged once when either:
            - A game enters debrief (game just ended, new one might start)
            - A lobby is at least half full (game about to start)

            With `lobby`, debrief alerts are suppressed — you'll only be pinged
            when a lobby is ready.
            """
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return

            user_id = ctx.author.id
            channel_id = ctx.channel.id
            username = str(ctx.author)

            # Parse arguments
            args_lower = args.lower().strip()
            tokens = [token for token in args_lower.split() if token]
            ptb_only = any(token == 'ptb' for token in tokens)
            modded_only = any(token in ('modded', 'mod', 'mfc') for token in tokens)
            newplayer_only = any(token in ('newplayer', 'new-player', 'np', 'beginner') for token in tokens)
            lobby_only = any(token in ('lobby', '--lobby', '-l') for token in tokens)
            skip_current_lobbies = any(token in ('--skip', '-skip', '-s', 'skip') for token in tokens)

            # Check if user is already waiting in this queue mode
            if server_monitor.is_user_waiting_for_next_game(user_id, ptb_only=ptb_only, modded_only=modded_only, newplayer_only=newplayer_only):
                embed = discord.Embed(
                    title="🔔 Already Waiting",
                    description="You're already on the notification list! I'll ping you when a game is ready.",
                    color=Config.EMBED_COLOR
                )
                
                # Show current wait time and mode status
                wait_info = server_monitor.get_next_game_waiter(user_id, ptb_only=ptb_only, modded_only=modded_only, newplayer_only=newplayer_only)
                if not wait_info:
                    await ctx.send("❌ Could not read your current waitlist status. Please try again.")
                    return
                wait_start = wait_info['timestamp']
                wait_duration = datetime.now(timezone.utc) - wait_start
                minutes_waiting = int(wait_duration.total_seconds() / 60)
                current_ptb_only = wait_info.get('ptb_only', False)
                current_modded_only = wait_info.get('modded_only', False)
                current_newplayer_only = wait_info.get('newplayer_only', False)
                current_lobby_only = wait_info.get('lobby_only', False)
                current_skip = bool(wait_info.get('skip_lobbies'))
                skip_names = server_monitor.resolve_server_names(wait_info.get('skip_lobbies', []), ptb_only=current_ptb_only, modded_only=current_modded_only, newplayer_only=current_newplayer_only) if current_skip else []

                embed.add_field(
                    name="⏱️ Waiting Time",
                    value=f"{minutes_waiting} minute(s)",
                    inline=False
                )

                if current_ptb_only:
                    embed.add_field(
                        name="🧪 Mode",
                        value="PTB servers only",
                        inline=False
                    )

                if current_modded_only:
                    embed.add_field(
                        name="🛠️ Modded Mode",
                        value="Modded servers only",
                        inline=False
                    )

                if current_newplayer_only:
                    embed.add_field(
                        name="🌱 New Player Mode",
                        value="New-player servers only",
                        inline=False
                    )

                if current_lobby_only:
                    embed.add_field(
                        name="🎯 Lobby Mode",
                        value="Lobby ready alerts only — debrief alerts are suppressed",
                        inline=False
                    )
                
                if current_skip:
                    skipped_list = ", ".join(skip_names[:5]) if skip_names else "current active lobbies"
                    if skip_names and len(skip_names) > 5:
                        skipped_list += f" (+{len(skip_names) - 5} more)"

                    embed.add_field(
                        name="⏭️ Skipping Current Lobbies",
                        value=(
                            "You won't be pinged for lobbies that were already active when you opted in.\n"
                            f"Skipping: {skipped_list}"
                        ),
                        inline=False
                    )
                
                embed.add_field(
                    name="Cancel",
                    value="Use `!cancelnextgame` to cancel your notification",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                return
            
            # Force update to get fresh server data before checking
            await server_monitor.force_update()
            
            # Add user to waitlist with queue-mode preferences
            skip_lobbies = server_monitor.get_joinable_lobby_ids(ptb_only=ptb_only, modded_only=modded_only, newplayer_only=newplayer_only) if skip_current_lobbies else []
            skip_lobby_names = server_monitor.resolve_server_names(skip_lobbies, ptb_only=ptb_only, modded_only=modded_only, newplayer_only=newplayer_only) if skip_lobbies else []
            server_monitor.add_next_game_waiter(
                user_id,
                channel_id,
                username,
                ptb_only=ptb_only,
                skip_lobbies=skip_lobbies,
                lobby_only=lobby_only,
                modded_only=modded_only,
                newplayer_only=newplayer_only
            )

            # Immediately check if there are any matching servers
            matching_servers = server_monitor.find_matching_servers_for_notification(ptb_only=ptb_only, modded_only=modded_only, newplayer_only=newplayer_only)

            if matching_servers:
                # Immediately notify the user
                notified = await server_monitor.notify_single_user_immediately(
                    user_id,
                    matching_servers,
                    ptb_only=ptb_only,
                    modded_only=modded_only,
                    newplayer_only=newplayer_only
                )
                if notified:
                    # User was notified, no need for extra confirmation message
                    return
            
            # No matching servers found, show confirmation message
            if lobby_only:
                title = "🧪🎯 PTB Lobby Notification Set!" if ptb_only else "🎯 Lobby Notification Set!"
                description = (
                    "I'll ping you here when a PTB (test branch) lobby is ready!"
                    if ptb_only else
                    "I'll ping you here when a lobby is ready!"
                )
            else:
                title = "🧪 PTB Notification Set!" if ptb_only else "🔔 Notification Set!"
                description = "I'll ping you here when a PTB (test branch) game is ready!" if ptb_only else "I'll ping you here when a game is ready!"

            embed = discord.Embed(
                title=title,
                description=description,
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )

            if skip_current_lobbies:
                skipped_list = ", ".join(skip_lobby_names[:5]) if skip_lobby_names else "current active lobbies"
                if skip_lobby_names and len(skip_lobby_names) > 5:
                    skipped_list += f" (+{len(skip_lobby_names) - 5} more)"

                skip_value = (
                    "I won't ping you for lobbies already active right now. "
                    "I'll notify you when a new lobby opens.\n"
                    if lobby_only else
                    "I won't ping you for lobbies already active right now. "
                    "I'll notify you when a new lobby opens or a game enters debrief.\n"
                )
                embed.add_field(
                    name="⏭️ Skip Current Lobbies",
                    value=f"{skip_value}Skipping: {skipped_list}",
                    inline=False
                )

            if lobby_only:
                notify_value = "• A lobby has 3+ players and is joinable (not full)\n"
            else:
                notify_value = (
                    "• A lobby has 3+ players and is joinable (not full)\n"
                    "• Another game enters debriefing (game just ended)\n"
                )
            embed.add_field(
                name="I'll notify you when:",
                value=notify_value,
                inline=False
            )

            if ptb_only:
                embed.add_field(
                    name="🧪 PTB Mode",
                    value="You'll only be notified about servers on the test branch (PTB)",
                    inline=False
                )

            if modded_only:
                embed.add_field(
                    name="🛠️ Modded Mode",
                    value="You'll only be notified about servers running mods",
                    inline=False
                )

            if newplayer_only:
                embed.add_field(
                    name="🌱 New Player Mode",
                    value="You'll only be notified about new-player servers",
                    inline=False
                )

            if lobby_only:
                embed.add_field(
                    name="🎯 Lobby Mode",
                    value="Debrief alerts are suppressed — you'll only be pinged when a lobby is ready",
                    inline=False
                )

            # Show current server status (filtered by queue mode if needed)
            servers_to_check = server_monitor.cached_servers
            if ptb_only:
                servers_to_check = [s for s in servers_to_check if s.get('is_test_branch', False)]
            if modded_only:
                servers_to_check = [s for s in servers_to_check if s.get('is_modded', False)]
            if newplayer_only:
                servers_to_check = [s for s in servers_to_check if s.get('is_new_player', False)]

            debrief_count = len([s for s in servers_to_check if s.get('status') == 'debrief'])
            joinable_lobbies = []
            for server in servers_to_check:
                if server.get('status') == 'lobby':
                    players = server.get('players', 0)
                    capacity = server.get('map_capacity', 8)
                    if players >= 3 and players < capacity:
                        joinable_lobbies.append(server)

            status_text = ""
            if debrief_count > 0 and not lobby_only:
                status_text += f"• {debrief_count} game(s) in debrief right now\n"
            if joinable_lobbies:
                status_text += f"• {len(joinable_lobbies)} joinable lobby(ies) with 3+ players right now\n"
            if not status_text:
                ptb_text = " (PTB servers)" if ptb_only else ""
                if lobby_only:
                    status_text = f"• No joinable lobbies with 3+ players currently{ptb_text}\n"
                else:
                    status_text = f"• No games in debrief or joinable lobbies with 3+ players currently{ptb_text}\n"
            
            embed.add_field(
                name="📊 Current Status",
                value=status_text.strip(),
                inline=False
            )
            
            waiters_count = server_monitor.get_next_game_waiters_count()
            embed.set_footer(text=f"{waiters_count} user(s) waiting for next game • Use !cancelnextgame to cancel")
            
            await ctx.send(embed=embed)

        @bot.command(name='cancelnextgame', aliases=['nextgamecancel'])
        async def cancel_next_game_notify(ctx):
            """Cancel your next game notification"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            user_id = ctx.author.id
            
            if server_monitor.remove_next_game_waiter(user_id):
                embed = discord.Embed(
                    title="✅ Notification Cancelled",
                    description="You've been removed from the notification list.",
                    color=Config.EMBED_COLOR
                )
                await ctx.send(embed=embed)
            else:
                embed = discord.Embed(
                    title="❌ Not on Waitlist",
                    description="You're not currently waiting for a notification. Use `!nextgame` to sign up!",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)

        @bot.event
        async def on_guild_join(guild):
            """Welcome a new guild with setup instructions."""
            logger.info(f"Joined guild '{guild.name}' (id={guild.id})")

            target = guild.system_channel
            if not target or not target.permissions_for(guild.me).send_messages:
                target = next(
                    (
                        ch for ch in guild.text_channels
                        if ch.permissions_for(guild.me).send_messages
                    ),
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
                    "`!stats`, `!nextgame`, `!graph`, `!formation`. Run `!status` for the full list."
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
                await ctx.send(
                    f"❌ Invalid usage. See `!help {ctx.command.qualified_name}` for examples."
                )
                return

            if isinstance(error, commands.CheckFailure):
                await ctx.send("❌ You can't use this command here.")
                return

            logger.error(f"Command error in {ctx.command}: {error}", exc_info=error)
            embed = discord.Embed(
                title="❌ Command Error",
                description="Something went wrong running that command. The error has been logged.",
                color=Config.EMBED_COLOR_NO_SERVERS
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

                await bot.start(Config.DISCORD_TOKEN)
            except KeyboardInterrupt:
                logger.info("Bot shutdown requested")
                self.stdout.write(self.style.WARNING('Bot shutdown requested'))
            except Exception as e:
                logger.error(f"Bot error: {e}")
                self.stdout.write(self.style.ERROR(f'Bot error: {e}'))
            finally:
                await bot.close()
                if connector:
                    await connector.close()

        # Run the bot
        try:
            asyncio.run(run_bot())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nBot stopped by user'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to start bot: {e}'))
            raise


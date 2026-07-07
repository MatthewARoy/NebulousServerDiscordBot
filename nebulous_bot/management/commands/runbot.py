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
import io
import os
import tempfile
import xml.etree.ElementTree as ET
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

# DELIBERATELY EAGER: this import pulls numpy + matplotlib (~100+ MiB RSS)
# at startup, BEFORE the event loop exists. Do NOT make it lazy to save
# memory — v2.3.4 tried exactly that, and the deferred import ran for
# minutes on the 1/8-OCPU VM at first !graph/!formation, starving the event
# loop (blocked heartbeats, gateway resets, every command hung). Paying the
# cost at boot, when nobody is connected, is the stable configuration.
from formation_optimizer import (
    optimize_fleet_file,
    create_formation_animation,
)

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
        
        def get_deployment_time() -> Optional[datetime]:
            """Get deployment time from environment variable or tracked bot start time"""
            nonlocal deployment_time
            
            # First, check for environment variable (set during deployment)
            deployment_time_str = os.getenv('DEPLOYMENT_TIME')
            if deployment_time_str:
                try:
                    # Try parsing ISO format timestamp
                    return datetime.fromisoformat(deployment_time_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    try:
                        # Try parsing Unix timestamp
                        return datetime.fromtimestamp(float(deployment_time_str), tz=timezone.utc)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse DEPLOYMENT_TIME: {deployment_time_str}")
            
            # Fall back to tracked bot start time
            return deployment_time
        
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

        @bot.command(name='restartmonitor', aliases=['restart'])
        @commands.has_permissions(administrator=True)
        async def restart_monitoring(ctx):
            """Restart the monitoring loop (admin only)"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            status_msg = await ctx.send("🔄 Restarting monitoring loop...")
            
            try:
                # Stop existing monitoring if running
                await server_monitor.stop_monitoring()
                await asyncio.sleep(1)
                
                # Start monitoring again
                await server_monitor.start_monitoring()
                
                # Verify it started
                task_running = server_monitor.monitoring_task and not server_monitor.monitoring_task.done()
                
                embed = discord.Embed(
                    title="✅ Monitoring Restarted",
                    description=f"The monitoring loop has been restarted successfully.\nTask running: {task_running}",
                    color=Config.EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )
                await status_msg.edit(content="", embed=embed)
                logger.info(f"Monitoring loop restarted by {ctx.author}. Task running: {task_running}")
            except Exception as e:
                logger.error(f"Error restarting monitoring: {e}", exc_info=True)
                await status_msg.edit(content=f"❌ Failed to restart monitoring: {str(e)}")
        
        @bot.command(name='debugmonitor')
        @commands.has_permissions(administrator=True)
        async def debug_monitor(ctx):
            """Show detailed monitoring loop debug info (admin only)"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            info = []
            info.append(f"**Server Monitor Initialized:** {'✅ Yes' if server_monitor else '❌ No'}")
            info.append(f"**Formatter Set:** {'✅ Yes' if server_monitor.formatter else '❌ No'}")
            info.append(f"**Monitoring Task:** {server_monitor.monitoring_task}")
            
            if server_monitor.monitoring_task:
                info.append(f"**Task Done:** {server_monitor.monitoring_task.done()}")
                if server_monitor.monitoring_task.done():
                    try:
                        exc = server_monitor.monitoring_task.exception()
                        info.append(f"**Task Exception:** {exc}")
                    except:
                        info.append("**Task Exception:** Unable to retrieve")
                else:
                    info.append("**Task Status:** Running")
            
            info.append(f"**Cached Servers:** {len(server_monitor.cached_servers)}")
            info.append(f"**Last Update:** {server_monitor.last_update}")
            info.append(f"**Config Update Interval:** {Config.UPDATE_INTERVAL}s")
            info.append(f"**Guilds Connected:** {len(bot.guilds)}")
            
            await ctx.send("**Monitoring Loop Debug Info:**\n" + "\n".join(info))

        @bot.command(name='status', aliases=['info'])
        async def bot_status(ctx):
            """Show bot status and information"""
            embed = discord.Embed(
                title="🤖 Nebulous Server Bot Status",
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )
            
            if server_monitor:
                last_update = server_monitor.last_update
                server_count = len(server_monitor.cached_servers)
                
                # Check if monitoring task is actually running
                task_status = "❌ Not Running"
                if server_monitor.monitoring_task:
                    if server_monitor.monitoring_task.done():
                        task_status = "❌ Stopped (check logs)"
                        try:
                            # Check if task had an exception
                            exc = server_monitor.monitoring_task.exception()
                            if exc:
                                task_status = f"❌ Failed: {str(exc)[:50]}"
                        except:
                            pass
                    else:
                        task_status = "✅ Running"
                
                embed.add_field(
                    name="📊 Server Monitoring",
                    value=f"**Task Status:** {task_status}\n**Servers Tracked:** {server_count}\n**Update Interval:** {Config.UPDATE_INTERVAL}s",
                    inline=True
                )
                
                if last_update:
                    embed.add_field(
                        name="🕒 Last Update",
                        value=f"<t:{int(last_update.timestamp())}:R>",
                        inline=True
                    )
            else:
                embed.add_field(
                    name="📊 Server Monitoring",
                    value="**Active:** ❌\n**Status:** Initializing...",
                    inline=True
                )
            
            # Add deployment time
            deployment_dt = get_deployment_time()
            if deployment_dt:
                embed.add_field(
                    name="🚀 Last Deployment",
                    value=f"<t:{int(deployment_dt.timestamp())}:R>",
                    inline=True
                )
            
            embed.add_field(
                name="🎮 Game",
                value=f"**{Config.GAME_NAME}**\nApp ID: {Config.NEBULOUS_APP_ID}",
                inline=True
            )
            
            embed.add_field(
                name="🔥 Commands",
                value=(
                    "`!listservers` - List all servers\n"
                    "`!openlobbies` - Show available servers\n"
                    "`!stats` - View game statistics\n"
                    "`!mapstats` - View map statistics\n"
                    "`!serverstats` - View server statistics\n"
                    "`!graph` - Display graphs of data over the last week\n"
                    "`!nextgame` - Get notified when a game is ready (options: `ptb`, `modded`, `newplayer`, `lobby`, `--skip`)\n"
                    "`!formation` - Optimize fleet formation file\n"
                    "`!refresh` - Force update\n"
                    "`!version` - Show version and changelog\n"
                    "`!status` - This message"
                ),
                inline=False
            )
            
            embed.set_footer(text="Bot running smoothly! • Created by Davaned")
            await ctx.send(embed=embed)

        @bot.command(name='version', aliases=['v', 'changelog'])
        async def show_version(ctx):
            """Show bot version and changelog"""
            embed = discord.Embed(
                title=f"🤖 Nebulous Server Bot v{Config.VERSION}",
                description="Current version and recent changes",
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Show current version
            embed.add_field(
                name="📌 Current Version",
                value=f"**v{Config.VERSION}**",
                inline=False
            )
            
            # Show concise recent changelog and keep within Discord field limits.
            lines = []
            for entry in Config.CHANGELOG[:3]:
                version = entry.get('version', 'Unknown')
                date = entry.get('date', 'Unknown')
                changes = entry.get('changes', [])

                lines.append(f"**v{version}** ({date})")
                for change in changes[:2]:
                    lines.append(f"• {change}")
                if len(changes) > 2:
                    lines.append(f"• +{len(changes) - 2} more")
                lines.append("")

            changelog_text = "\n".join(lines).strip() or "No changelog available"
            if len(changelog_text) > 1000:
                changelog_text = changelog_text[:997].rstrip() + "..."
            
            embed.add_field(
                name="📋 Recent Changes",
                value=changelog_text,
                inline=False
            )
            
            embed.set_footer(text="Use !status to see bot information and commands")
            await ctx.send(embed=embed)

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

        @bot.command(name='commandlogs', aliases=['cmdlogs', 'logs'], hidden=True)
        @commands.is_owner()
        async def show_command_logs(ctx, limit: int = 20, command_filter: str = None):
            """
            View command usage logs (bot owner only — exposes cross-guild usage data)
            
            Usage: !commandlogs [limit] [command_name]
            Examples: !commandlogs 10, !commandlogs 50 stats
            """
            from nebulous_bot.models import CommandLog
            from django.db.models import Count
            from asgiref.sync import sync_to_async
            
            # Limit to prevent abuse
            limit = min(limit, 100)
            
            @sync_to_async
            def get_command_logs():
                logs = CommandLog.objects.all().order_by('-timestamp')
                
                # Filter by command if specified
                if command_filter:
                    logs = logs.filter(command_name__icontains=command_filter)
                
                # Get recent logs
                recent_logs = list(logs[:limit])
                
                # Get summary stats
                total_count = CommandLog.objects.count()
                success_count = CommandLog.objects.filter(success=True).count()
                error_count = CommandLog.objects.filter(success=False).count()
                
                # Get top commands
                top_commands = list(
                    CommandLog.objects.values('command_name')
                    .annotate(count=Count('id'))
                    .order_by('-count')[:5]
                )
                
                # Get context breakdown (guild vs DM)
                guild_commands = CommandLog.objects.filter(context_type='guild').count()
                dm_commands = CommandLog.objects.filter(context_type='dm').count()
                thread_commands = CommandLog.objects.filter(context_type='thread').count()
                
                # Get unique users by context
                guild_users = CommandLog.objects.filter(context_type='guild').values('user_id').distinct().count()
                dm_users = CommandLog.objects.filter(context_type='dm').values('user_id').distinct().count()
                thread_users = CommandLog.objects.filter(context_type='thread').values('user_id').distinct().count()
                
                # Total unique users who have used DMs
                total_dm_users = CommandLog.objects.filter(context_type='dm').values('user_id').distinct().count()
                
                # Total unique users overall
                total_unique_users = CommandLog.objects.values('user_id').distinct().count()
                
                return recent_logs, total_count, success_count, error_count, top_commands, \
                       guild_commands, dm_commands, thread_commands, \
                       guild_users, dm_users, thread_users, total_dm_users, total_unique_users
            
            try:
                logs, total, success, errors, top_commands, \
                guild_commands, dm_commands, thread_commands, \
                guild_users, dm_users, thread_users, total_dm_users, total_unique_users = await get_command_logs()
                
                if not logs:
                    embed = discord.Embed(
                        title="📋 Command Logs",
                        description="No command logs found yet.",
                        color=Config.EMBED_COLOR_NO_SERVERS
                    )
                    await ctx.send(embed=embed)
                    return
                
                embed = discord.Embed(
                    title=f"📋 Command Logs (Last {len(logs)})",
                    color=Config.EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )
                
                # Summary statistics
                embed.add_field(
                    name="📊 Summary",
                    value=(
                        f"**Total Commands:** {total:,}\n"
                        f"**Successful:** {success:,} ({success*100//total if total > 0 else 0}%)\n"
                        f"**Errors:** {errors:,} ({errors*100//total if total > 0 else 0}%)"
                    ),
                    inline=True
                )
                
                # Context breakdown (Guild vs DM)
                context_text = (
                    f"**Servers:** {guild_commands:,} ({guild_commands*100//total if total > 0 else 0}%)\n"
                    f"**DMs:** {dm_commands:,} ({dm_commands*100//total if total > 0 else 0}%)\n"
                )
                if thread_commands > 0:
                    context_text += f"**Threads:** {thread_commands:,} ({thread_commands*100//total if total > 0 else 0}%)"
                
                embed.add_field(
                    name="📍 Usage by Location",
                    value=context_text,
                    inline=True
                )
                
                # User breakdown
                user_text = (
                    f"**Server Users:** {guild_users:,}\n"
                    f"**DM Users:** {dm_users:,}\n"
                    f"**Total Unique:** {total_unique_users:,}"
                )
                if thread_users > 0:
                    user_text = user_text.replace("**Total Unique:**", f"**Thread Users:** {thread_users:,}\n**Total Unique:**")
                
                embed.add_field(
                    name="👥 Unique Users",
                    value=user_text,
                    inline=True
                )
                
                # Top commands
                if top_commands:
                    top_text = "\n".join([
                        f"**{i+1}.** `{cmd['command_name']}`: {cmd['count']}"
                        for i, cmd in enumerate(top_commands)
                    ])
                    embed.add_field(
                        name="🔥 Top Commands",
                        value=top_text,
                        inline=False
                    )
                
                # Recent logs (show first 10 in detail)
                log_text = ""
                for i, log in enumerate(logs[:10], 1):
                    status = "✅" if log.success else f"❌ {log.error_type}"
                    location = log.context_type
                    if log.guild_name:
                        location = f"{log.guild_name[:20]}"
                    elif log.guild_id:
                        location = f"Guild {log.guild_id}"
                    
                    time_str = log.timestamp.strftime("%m/%d %H:%M")
                    latency = f"{log.latency_ms}ms" if log.latency_ms else "N/A"
                    
                    log_text += f"**{i}.** `{log.command_name}` by {log.user_name[:15]}\n"
                    log_text += f"   {status} • {location} • {time_str} • {latency}\n"
                
                if len(logs) > 10:
                    log_text += f"\n*... and {len(logs) - 10} more*"
                
                embed.add_field(
                    name="📝 Recent Commands",
                    value=log_text,
                    inline=False
                )
                
                if command_filter:
                    embed.set_footer(text=f"Filtered by: {command_filter}")
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Error fetching command logs: {e}", exc_info=True)
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"Failed to fetch command logs: {str(e)}",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)
        
        @bot.command(name='formation', aliases=['form', 'optimize'])
        @commands.cooldown(1, 30, commands.BucketType.user)
        async def optimize_formation(ctx, *, args: str = None):
            """
            Optimize a fleet formation file by compacting ships while maintaining minimum distance.
            
            Usage: !formation [min_radius_meters] [-skip] [-planar] [-symmetrical] [-arcs]
            - Attach a .fleet XML file to your message
            - Optional: specify minimum radius in meters (default: 350 meters)
            - Optional: use -skip to skip image generation (faster)
            - Optional: use -planar for flat formation facing forward
            - Optional: use -symmetrical for more symmetrical formation
            - Optional: use -arcs to keep forward firing arcs clear for armed ships
            - Returns the optimized fleet file
            
            Example: !formation 350  (for 350 meters)
            Example: !formation 500 -planar  (planar formation)
            Example: !formation 350 -symmetrical -skip  (symmetrical, skip images)
            Example: !formation 350 -arcs  (keep firing arcs clear)
            """
            # Parse arguments
            skip_images = False
            planar = False
            symmetrical = False
            clear_arcs = False
            min_radius_meters = 350.0
            
            if args:
                args_lower = args.lower()
                
                # Check for flags
                if '-skip' in args_lower:
                    skip_images = True
                    args_lower = args_lower.replace('-skip', '')
                if '-planar' in args_lower:
                    planar = True
                    args_lower = args_lower.replace('-planar', '')
                if '-symmetrical' in args_lower or '-symmetric' in args_lower:
                    symmetrical = True
                    args_lower = args_lower.replace('-symmetrical', '').replace('-symmetric', '')
                if '-arcs' in args_lower or '-cleararcs' in args_lower:
                    clear_arcs = True
                    args_lower = args_lower.replace('-arcs', '').replace('-cleararcs', '')
                
                # Clean up and parse min_radius_meters
                args_clean = args_lower.strip()
                if args_clean:
                    try:
                        min_radius_meters = float(args_clean)
                    except ValueError:
                        # If parsing fails, use default
                        pass
            # Check for attachments
            if not ctx.message.attachments:
                embed = discord.Embed(
                    title="❌ No File Attached",
                    description="Please attach a fleet (.fleet) XML file to your message.",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                embed.add_field(
                    name="Usage",
                    value="`!formation [min_radius] [-skip] [-planar] [-symmetrical] [-arcs]`\nAttach a .fleet file to optimize it.\n- `-skip`: Skip image generation\n- `-planar`: Flat formation facing forward\n- `-symmetrical`: More symmetrical formation\n- `-arcs`: Keep forward firing arcs clear for armed ships",
                    inline=False
                )
                await ctx.send(embed=embed)
                return
            
            # Get the first attachment
            attachment = ctx.message.attachments[0]
            
            # Validate file extension
            if not attachment.filename.lower().endswith('.fleet'):
                embed = discord.Embed(
                    title="❌ Invalid File Type",
                    description=f"Expected a .fleet file, got: {attachment.filename}",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)
                return
            
            # Validate min_radius_meters (user input is in meters)
            if min_radius_meters <= 0:
                embed = discord.Embed(
                    title="❌ Invalid Minimum Radius",
                    description="Minimum radius must be greater than 0 meters.",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)
                return
            
            # Show processing message
            processing_msg = await ctx.send("🔄 Processing fleet file...")
            
            try:
                # Download the file
                file_content = await attachment.read()
                
                # Create temporary file for input
                with tempfile.NamedTemporaryFile(mode='wb', suffix='.fleet', delete=False) as temp_input:
                    temp_input.write(file_content)
                    temp_input_path = temp_input.name
                
                try:
                    # Validate XML structure before processing
                    try:
                        tree = ET.parse(temp_input_path)
                        root = tree.getroot()
                        
                        # Check for required elements
                        if root.find("Name") is None:
                            raise ValueError("Fleet file missing <Name> element")
                        
                        # Check for at least one Ship element
                        ships = list(root.iter("Ship"))
                        if not ships:
                            raise ValueError("Fleet file contains no <Ship> elements")
                        
                        # Check for InitialFormation elements
                        formations_found = False
                        for ship in ships:
                            if ship.find("InitialFormation") is not None:
                                formations_found = True
                                break
                        
                        if not formations_found:
                            raise ValueError("Fleet file contains no <InitialFormation> elements")
                        
                    except ET.ParseError as e:
                        raise ValueError(f"Invalid XML format: {str(e)}") from e
                    
                    # Optimize the fleet file
                    # Only capture animation if we're generating images
                    # min_radius_meters is already in meters (user-facing)
                    optimization_result = optimize_fleet_file(
                        temp_input_path, 
                        min_distance_meters=min_radius_meters, 
                        capture_animation=not skip_images,
                        planar=planar,
                        symmetrical=symmetrical,
                        clear_arcs=clear_arcs
                    )
                    
                    # Unpack results (with or without animation states)
                    if len(optimization_result) == 5:
                        optimized_path, before_positions, after_positions, ship_names, intermediate_states = optimization_result
                    else:
                        optimized_path, before_positions, after_positions, ship_names = optimization_result
                        intermediate_states = None
                    
                    # Generate GIF animation only if not skipping images
                    gif_bytes = None
                    gif_path = None
                    
                    if not skip_images:
                        # Generate GIF animation (run in executor to avoid blocking)
                        def generate_gif():
                            # Generate GIF animation if we have intermediate states
                            gif_path = None
                            gif_bytes = None
                            if intermediate_states:
                                try:
                                    # Create temporary file for GIF
                                    gif_temp = tempfile.NamedTemporaryFile(suffix='.gif', delete=False)
                                    gif_path = gif_temp.name
                                    gif_temp.close()
                                    
                                    # Generate GIF from intermediate states (all positions already in meters)
                                    create_formation_animation(
                                        before_positions,
                                        intermediate_states,
                                        ship_names,
                                        min_radius_meters,
                                        output_path=gif_path,
                                        fps=10,
                                        duration_ms=100
                                    )
                                    
                                    # Read GIF bytes
                                    with open(gif_path, 'rb') as f:
                                        gif_bytes = f.read()
                                except Exception as gif_error:
                                    logger.warning(f"Failed to generate GIF animation: {gif_error}")
                                    # Continue without GIF if generation fails
                            else:
                                logger.warning("No intermediate states available for GIF generation")
                            
                            return gif_bytes, gif_path
                        
                        import concurrent.futures
                        loop = asyncio.get_event_loop()
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            gif_bytes, gif_path = await loop.run_in_executor(executor, generate_gif)
                    
                    # Read the optimized file
                    with open(optimized_path, 'rb') as f:
                        optimized_content = f.read()
                    
                    # Create Discord file objects
                    optimized_filename = attachment.filename.replace('.fleet', f'_Optimized_{int(min_radius_meters)}m.fleet')
                    discord_file = discord.File(
                        io.BytesIO(optimized_content),
                        filename=optimized_filename
                    )
                    
                    # Prepare files list
                    files_to_send = [discord_file]
                    
                    # Add GIF if generated successfully and not skipping images
                    discord_gif_file = None
                    if not skip_images:
                        if gif_bytes:
                            gif_filename = attachment.filename.replace('.fleet', f'_animation_{int(min_radius_meters)}m.gif')
                            discord_gif_file = discord.File(
                                io.BytesIO(gif_bytes),
                                filename=gif_filename
                            )
                            files_to_send.append(discord_gif_file)
                        else:
                            # If GIF generation failed, send error message
                            embed_error = discord.Embed(
                                title="⚠️ Optimization Complete",
                                description="Fleet optimized but animation generation failed.",
                                color=Config.EMBED_COLOR_NO_SERVERS
                            )
                            await processing_msg.edit(content="", embed=embed_error)
                            return
                    
                    # Create success embed
                    variant_info = []
                    if planar:
                        variant_info.append("Planar")
                    if symmetrical:
                        variant_info.append("Symmetrical")
                    variant_text = f" ({', '.join(variant_info)})" if variant_info else ""
                    
                    embed = discord.Embed(
                        title="✅ Formation Optimized",
                        description=f"Fleet formation optimized with minimum radius of **{min_radius_meters:.0f} meters**{variant_text}.",
                        color=Config.EMBED_COLOR,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.add_field(
                        name="Original File",
                        value=attachment.filename,
                        inline=True
                    )
                    embed.add_field(
                        name="Minimum Radius",
                        value=f"{min_radius_meters:.0f} meters",
                        inline=True
                    )
                    embed.add_field(
                        name="Ships Processed",
                        value=str(len(ships)),
                        inline=True
                    )
                    if variant_info:
                        embed.add_field(
                            name="Formation Variant",
                            value=", ".join(variant_info),
                            inline=False
                        )
                    
                    # Set GIF as image in embed (only if not skipping)
                    if not skip_images and gif_bytes:
                        gif_filename = attachment.filename.replace('.fleet', f'_animation_{int(min_radius_meters)}m.gif')
                        embed.set_image(url=f"attachment://{gif_filename}")
                    
                    # Update footer based on whether images were generated
                    if skip_images:
                        embed.set_footer(text="The optimized fleet file is attached below")
                    else:
                        embed.set_footer(text="The optimized fleet file and animation GIF are attached below")
                    
                    # Delete processing message and send result
                    await processing_msg.delete()
                    await ctx.send(embed=embed, files=files_to_send)
                    
                    # Clean up temporary GIF file
                    if gif_path and os.path.exists(gif_path):
                        try:
                            os.unlink(gif_path)
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup GIF temp file: {cleanup_error}")
                    
                finally:
                    # Clean up temporary files
                    try:
                        os.unlink(temp_input_path)
                        if os.path.exists(optimized_path):
                            os.unlink(optimized_path)
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to cleanup temp files: {cleanup_error}")
                
            except ValueError as e:
                # Validation errors
                embed = discord.Embed(
                    title="❌ Invalid Fleet File",
                    description=str(e),
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await processing_msg.edit(content="", embed=embed)
            except Exception as e:
                # Other errors
                logger.error(f"Error optimizing formation: {e}", exc_info=True)
                embed = discord.Embed(
                    title="❌ Processing Error",
                    description=f"Failed to optimize fleet file: {str(e)}",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await processing_msg.edit(content="", embed=embed)
        
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


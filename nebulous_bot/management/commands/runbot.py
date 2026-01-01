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
from datetime import datetime, timezone
from typing import Optional
from django.core.management.base import BaseCommand

from nebulous_bot.config import Config
from nebulous_bot.server_monitor import ServerMonitor
from nebulous_bot.server_formatter import ServerFormatter
from nebulous_bot.models import BotStatus
from nebulous_bot.command_logging import setup_command_metrics

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
        command_metrics_logger = setup_command_metrics(bot)
        
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

        @bot.command(name='listservers', aliases=['ls', 'servers'])
        async def list_servers(ctx, *, filter_args: str = ""):
            """List all active servers with optional filtering"""
            if not server_monitor or not formatter:
                await ctx.send("❌ Server monitoring not initialized yet. Please wait a moment.")
                return
            
            # Always fetch fresh data from Steam
            await server_monitor.force_update()
            
            # Parse filter arguments
            filters = {}
            show_all = False
            if filter_args:
                args = filter_args.lower().split()
                if 'all' in args:
                    show_all = True
                if 'open' in args:
                    filters['open_lobby'] = True
                if 'lobby' in args:
                    filters['status'] = 'lobby'
                if 'ingame' in args:
                    filters['status'] = 'in_game'
                if 'us' in args:
                    filters['region'] = 'us'
                if 'eu' in args:
                    filters['region'] = 'eu'
                if 'competitive' in args:
                    filters['game_mode'] = 'competitive'
                if 'casual' in args:
                    filters['game_mode'] = 'casual'
            
            # Get servers - use all servers if "all" is specified, otherwise use filtered cache
            if show_all:
                base_servers = server_monitor.cached_all_servers
            else:
                base_servers = server_monitor.cached_servers
            
            # Apply additional filters if specified
            if filters:
                # Apply filters to the base server list
                filtered_servers = []
                for server in base_servers:
                    match = True
                    
                    if filters.get('open_lobby'):
                        if server.get('status') != 'lobby' or server.get('players', 0) >= server.get('map_capacity', 8):
                            match = False
                    
                    if filters.get('status') and server.get('status') != filters['status']:
                        match = False
                    
                    if filters.get('region') and server.get('region', '').lower() != filters['region'].lower():
                        match = False
                    
                    if filters.get('game_mode'):
                        game_mode = server.get('game_mode', '').lower()
                        if filters['game_mode'].lower() == 'competitive' and 'competitive' not in game_mode:
                            match = False
                        elif filters['game_mode'].lower() == 'casual' and 'casual' not in game_mode:
                            match = False
                    
                    if match:
                        filtered_servers.append(server)
                
                servers = filtered_servers
                title_suffix = f" (Filtered: {filter_args})"
            else:
                servers = base_servers
                if show_all:
                    title_suffix = " (All Servers)"
                else:
                    title_suffix = ""
            
            base_title = f"🚀 {Config.GAME_NAME} - Active Servers{title_suffix}"
            # Add Discord timestamp format to title
            update_time = server_monitor.last_update or datetime.now(timezone.utc)
            timestamp_int = int(update_time.timestamp())
            title = f"{base_title} @ <t:{timestamp_int}:R>"
            description = f"Found {len(servers)} servers" if servers else "No servers match your criteria."
            embed = formatter.create_server_list_embed(
                servers, title, description, max_servers=15, 
                last_update=server_monitor.last_update, 
                game_start_times=server_monitor.game_start_times
            )
            
            # Add filter help
            footer_text = "Filters: open, lobby, ingame, us, eu, competitive, casual, all • Use !openlobbies for joinable servers"
            embed.set_footer(text=footer_text)
            message = await ctx.send(embed=embed)
            await server_monitor.track_message(message)

        @bot.command(name='openlobbies', aliases=['open', 'available'])
        async def open_lobbies(ctx):
            """List servers with available player slots"""
            if not server_monitor or not formatter:
                await ctx.send("❌ Server monitoring not initialized yet. Please wait a moment.")
                return
            
            # Always fetch fresh data from Steam
            await server_monitor.force_update()
            
            open_servers = server_monitor.get_open_lobbies()
            embed = formatter.create_lobby_list_embed(open_servers, server_monitor.last_update)
            message = await ctx.send(embed=embed)
            await server_monitor.track_message(message)

        @bot.command(name='refresh', aliases=['update'])
        async def refresh_servers(ctx):
            """Force refresh the server list"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            refresh_msg = await ctx.send("🔄 Refreshing server list...")
            
            try:
                await server_monitor.force_update()
                
                # Log status to database (async-safe)
                try:
                    from asgiref.sync import sync_to_async
                    
                    @sync_to_async
                    def log_status():
                        BotStatus.objects.create(
                            total_servers=len(server_monitor.cached_servers),
                            total_players=sum(s.get('players', 0) for s in server_monitor.cached_servers),
                            open_lobbies=len(server_monitor.get_open_lobbies())
                        )
                    
                    await log_status()
                except Exception as db_error:
                    logger.warning(f"Failed to log bot status to database: {db_error}")
                
                embed = discord.Embed(
                    title="✅ Server List Refreshed",
                    description=f"Updated {len(server_monitor.cached_servers)} servers",
                    color=Config.EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )
                await refresh_msg.edit(content="", embed=embed)
            except Exception as e:
                logger.error(f"Error refreshing servers: {e}")
                await refresh_msg.edit(content="❌ Failed to refresh server list. Check logs for details.")

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
                        info.append(f"**Task Exception:** Unable to retrieve")
                else:
                    info.append(f"**Task Status:** Running")
            
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
                    "`!nextgame` - Get notified when a game is ready\n"
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
            
            # Show recent changelog (last 3 versions)
            changelog_text = ""
            for entry in Config.CHANGELOG[:3]:
                version = entry.get('version', 'Unknown')
                date = entry.get('date', 'Unknown')
                changes = entry.get('changes', [])
                
                changelog_text += f"**v{version}** ({date})\n"
                for change in changes:
                    changelog_text += f"• {change}\n"
                changelog_text += "\n"
            
            embed.add_field(
                name="📋 Recent Changes",
                value=changelog_text.strip() or "No changelog available",
                inline=False
            )
            
            embed.set_footer(text="Use !status to see bot information and commands")
            await ctx.send(embed=embed)

        @bot.command(name='stats', aliases=['statistics'])
        async def show_statistics(ctx, timeframe: str = "all"):
            """Show general game statistics"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            from nebulous_bot.models import GameSession, PlayerSnapshot
            from django.db.models import Count, Avg, Sum
            from django.utils import timezone as django_timezone
            from datetime import timedelta
            from asgiref.sync import sync_to_async
            import pytz
            
            # PST timezone for consistent display
            pst = pytz.timezone('America/Los_Angeles')
            
            @sync_to_async
            def get_statistics():
                import pytz
                pst = pytz.timezone('America/Los_Angeles')
                
                # Calculate timeframe
                now = django_timezone.now()
                if timeframe == "today":
                    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    timeframe_text = "Today"
                elif timeframe == "week":
                    start_date = now - timedelta(days=7)
                    timeframe_text = "Past 7 Days"
                elif timeframe == "month":
                    start_date = now - timedelta(days=30)
                    timeframe_text = "Past 30 Days"
                else:
                    start_date = None
                    timeframe_text = "All Time"
                
                # Query database
                games = GameSession.objects.filter(is_valid_game=True)
                if start_date:
                    games = games.filter(game_start__gte=start_date)
                
                total_games = games.count()
                
                # Always get today's games count for the default view (using PST timezone)
                games_today = 0
                if timeframe == "all":
                    # Get current time in PST, set to midnight PST, then convert to UTC for database query
                    now_pst = now.astimezone(pst)
                    today_start_pst = now_pst.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_start_utc = today_start_pst.astimezone(timezone.utc)
                    games_today = GameSession.objects.filter(
                        is_valid_game=True,
                        game_start__gte=today_start_utc
                    ).count()
                
                if total_games == 0:
                    return None, timeframe_text
                
                # Calculate statistics
                stats = games.aggregate(
                    avg_duration=Avg('duration_seconds'),
                    total_duration=Sum('duration_seconds'),
                    avg_players=Avg('players_at_start')
                )
                
                # Get player count statistics
                player_snapshots = PlayerSnapshot.objects.all()
                if start_date:
                    player_snapshots = player_snapshots.filter(timestamp__gte=start_date)
                
                player_stats = player_snapshots.aggregate(
                    avg_players=Avg('total_players')
                )
                
                # Get actual max
                max_players_snapshot = player_snapshots.order_by('-total_players').first()
                max_players = max_players_snapshot.total_players if max_players_snapshot else 0
                
                # Get most recent snapshot
                recent_snapshot = PlayerSnapshot.objects.order_by('-timestamp').first()
                
                # Get first game for "tracked since" timestamp (for all-time stats only)
                first_game = None
                if timeframe == "all":
                    first_game = GameSession.objects.filter(is_valid_game=True).order_by('game_start').first()
                
                # Top 3 maps
                top_maps = games.values('map_name').annotate(
                    count=Count('id')
                ).order_by('-count')[:3]
                
                return {
                    'total_games': total_games,
                    'games_today': games_today,
                    'stats': stats,
                    'player_stats': player_stats,
                    'max_players': max_players,
                    'recent_snapshot': recent_snapshot,
                    'first_game': first_game,
                    'top_maps': list(top_maps)
                }, timeframe_text
            
            result, timeframe_text = await get_statistics()
            
            if result is None:
                embed = discord.Embed(
                    title=f"📊 Game Statistics - {timeframe_text}",
                    description="No game data available yet. Games are tracked once they complete (5+ minutes).",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)
                return
            
            # Create embed
            embed = discord.Embed(
                title=f"📊 Game Statistics - {timeframe_text}",
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Add "tracked since" to description for all-time stats
            if timeframe == "all" and result.get('first_game'):
                first_game = result['first_game']
                # Convert to PST for display
                first_game_pst = first_game.game_start.astimezone(pst)
                tracked_since = first_game_pst.strftime("%B %d, %Y at %I:%M %p PST")
                embed.description = f"📅 *Stats tracked since {tracked_since}*"
            
            # Game statistics
            avg_duration_mins = int(result['stats']['avg_duration'] / 60) if result['stats']['avg_duration'] else 0
            total_duration_hours = int(result['stats']['total_duration'] / 3600) if result['stats']['total_duration'] else 0
            
            # Build games played text with optional "Games Today" for all-time view
            games_text = f"**Total Games:** {result['total_games']:,}\n"
            if timeframe == "all" and result.get('games_today', 0) > 0:
                games_text += f"**Games Today:** {result['games_today']:,}\n"
            games_text += f"**Avg Duration:** {avg_duration_mins} minutes\n"
            games_text += f"**Total Playtime:** {total_duration_hours:,} hours"
            
            embed.add_field(
                name="🎮 Games Played",
                value=games_text,
                inline=True
            )
            
            # Player statistics
            avg_players = result['player_stats']['avg_players'] or 0
            avg_players_game = result['stats']['avg_players'] or 0
            embed.add_field(
                name="👥 Player Activity",
                value=(
                    f"**Avg Players Online:** {avg_players:.1f}\n"
                    f"**Peak Players:** {result['max_players']}\n"
                    f"**Avg Players/Game:** {avg_players_game:.1f}"
                ),
                inline=True
            )
            
            # Current stats
            if result['recent_snapshot']:
                snap = result['recent_snapshot']
                embed.add_field(
                    name="📈 Current Status",
                    value=(
                        f"**Players Online:** {snap.total_players}\n"
                        f"**Active Servers:** {snap.total_servers}\n"
                        f"**Games In Progress:** {snap.games_in_progress}"
                    ),
                    inline=True
                )
            
            # Top 3 maps
            if result['top_maps']:
                map_text = "\n".join([
                    f"**{i+1}.** {m['map_name']}: {m['count']} games"
                    for i, m in enumerate(result['top_maps'])
                ])
                embed.add_field(
                    name="🗺️ Most Played Maps",
                    value=map_text,
                    inline=False
                )
            
            embed.set_footer(text="Use !mapstats for detailed map statistics • !serverstats for server statistics • Reach out to Davaned for more info")
            await ctx.send(embed=embed)

        @bot.command(name='mapstats', aliases=['maps'])
        async def show_map_statistics(ctx, limit: int = 10):
            """Show map play frequency statistics (calculated from games in real-time)"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            from nebulous_bot.models import GameSession
            from django.db.models import Count, Avg, Max
            from asgiref.sync import sync_to_async
            
            @sync_to_async
            def get_map_stats():
                return list(GameSession.objects.filter(is_valid_game=True).values('map_name').annotate(
                    total_games=Count('id'),
                    avg_duration=Avg('duration_seconds'),
                    avg_players=Avg('players_at_start'),
                    last_played=Max('game_start')
                ).order_by('-total_games')[:limit])
            
            map_stats = await get_map_stats()
            
            if not map_stats:
                embed = discord.Embed(
                    title="🗺️ Map Statistics",
                    description="No map data available yet. Maps are tracked as games complete.",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"🗺️ Map Play Frequency (Top {limit})",
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )
            
            for i, map_stat in enumerate(map_stats, 1):
                avg_duration_mins = int(map_stat['avg_duration'] / 60) if map_stat['avg_duration'] else 0
                last_played_text = f"<t:{int(map_stat['last_played'].timestamp())}:R>" if map_stat['last_played'] else "Never"
                
                embed.add_field(
                    name=f"{i}. {map_stat['map_name']}",
                    value=(
                        f"**Games:** {map_stat['total_games']}\n"
                        f"**Avg Duration:** {avg_duration_mins}m\n"
                        f"**Avg Players:** {map_stat['avg_players']:.1f}\n"
                        f"**Last Played:** {last_played_text}"
                    ),
                    inline=True
                )
            
            embed.set_footer(text="Only valid games (5+ minutes) are counted • Calculated in real-time")
            await ctx.send(embed=embed)

        @bot.command(name='serverstats', aliases=['serverinfo'])
        async def show_server_statistics(ctx, limit: int = 10):
            """Show server usage statistics (calculated from games in real-time)"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            from nebulous_bot.models import GameSession
            from django.db.models import Count, Avg, Max
            from asgiref.sync import sync_to_async
            
            @sync_to_async
            def get_server_stats():
                stats = list(GameSession.objects.filter(is_valid_game=True).values('server_id', 'server_name').annotate(
                    total_games=Count('id'),
                    avg_players=Avg('players_at_start'),
                    last_game=Max('game_start')
                ).order_by('-total_games')[:limit])
                
                # Calculate player-hours for each server
                for stat in stats:
                    games = GameSession.objects.filter(
                        server_id=stat['server_id'],
                        is_valid_game=True,
                        duration_seconds__isnull=False
                    )
                    stat['player_hours'] = sum(g.players_at_start * g.duration_seconds / 3600 for g in games)
                
                return stats
            
            server_stats = await get_server_stats()
            
            if not server_stats:
                embed = discord.Embed(
                    title="🖥️ Server Statistics",
                    description="No server data available yet. Servers are tracked as games complete.",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"🖥️ Server Usage Statistics (Top {limit})",
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )
            
            for i, srv_stat in enumerate(server_stats, 1):
                last_game_text = f"<t:{int(srv_stat['last_game'].timestamp())}:R>" if srv_stat['last_game'] else "Never"
                player_hours = int(srv_stat['player_hours'])
                
                # Truncate long server names
                server_name = srv_stat['server_name'][:40] + "..." if len(srv_stat['server_name']) > 40 else srv_stat['server_name']
                
                embed.add_field(
                    name=f"{i}. {server_name}",
                    value=(
                        f"**Games:** {srv_stat['total_games']}\n"
                        f"**Avg Players:** {srv_stat['avg_players']:.1f}\n"
                        f"**Player-Hours:** {player_hours:,}\n"
                        f"**Last Game:** {last_game_text}"
                    ),
                    inline=True
                )
            
            embed.set_footer(text="Only valid games (5+ minutes) are counted • Calculated in real-time")
            await ctx.send(embed=embed)

        @bot.command(name='nextgame', aliases=['notify', 'notifyme', 'ng'])
        async def next_game_notify(ctx, *, args: str = ""):
            """
            Get notified when the next game is ready to join.
            
            Usage: !nextgame [ptb]
            - !nextgame - Notify for all servers
            - !nextgame ptb - Notify only for PTB (test branch) servers
            
            You'll be pinged once when either:
            - A game enters debrief (game just ended, new one might start)
            - A lobby is at least half full (game about to start)
            """
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            user_id = ctx.author.id
            channel_id = ctx.channel.id
            username = str(ctx.author)
            
            # Parse arguments
            args_lower = args.lower().strip()
            ptb_only = args_lower == 'ptb'
            
            # Check if user is already waiting
            if user_id in server_monitor.next_game_waiters:
                embed = discord.Embed(
                    title="🔔 Already Waiting",
                    description="You're already on the notification list! I'll ping you when a game is ready.",
                    color=Config.EMBED_COLOR
                )
                
                # Show current wait time and PTB status
                wait_info = server_monitor.next_game_waiters[user_id]
                wait_start = wait_info['timestamp']
                wait_duration = datetime.now(timezone.utc) - wait_start
                minutes_waiting = int(wait_duration.total_seconds() / 60)
                current_ptb_only = wait_info.get('ptb_only', False)
                
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
                
                embed.add_field(
                    name="Cancel",
                    value="Use `!cancelnextgame` to cancel your notification",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                return
            
            # Force update to get fresh server data before checking
            await server_monitor.force_update()
            
            # Add user to waitlist with PTB preference
            server_monitor.add_next_game_waiter(user_id, channel_id, username, ptb_only=ptb_only)
            
            # Immediately check if there are any matching servers
            matching_servers = server_monitor.find_matching_servers_for_notification(ptb_only=ptb_only)
            
            if matching_servers:
                # Immediately notify the user
                notified = await server_monitor.notify_single_user_immediately(user_id, matching_servers)
                if notified:
                    # User was notified, no need for extra confirmation message
                    return
            
            # No matching servers found, show confirmation message
            title = "🧪 PTB Notification Set!" if ptb_only else "🔔 Notification Set!"
            description = "I'll ping you here when a PTB (test branch) game is ready!" if ptb_only else "I'll ping you here when a game is ready!"
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="I'll notify you when:",
                value=(
                    "• A lobby has 3+ players and is joinable (not full)\n"
                    "• Another game enters debriefing (game just ended)\n"
                ),
                inline=False
            )
            
            if ptb_only:
                embed.add_field(
                    name="🧪 PTB Mode",
                    value="You'll only be notified about servers on the test branch (PTB)",
                    inline=False
                )
            
            # Show current server status (filtered by PTB if needed)
            servers_to_check = server_monitor.cached_servers
            if ptb_only:
                servers_to_check = [s for s in servers_to_check if s.get('is_test_branch', False)]
            
            debrief_count = len([s for s in servers_to_check if s.get('status') == 'debrief'])
            joinable_lobbies = []
            for server in servers_to_check:
                if server.get('status') == 'lobby':
                    players = server.get('players', 0)
                    capacity = server.get('map_capacity', 8)
                    if players >= 3 and players < capacity:
                        joinable_lobbies.append(server)
            
            status_text = ""
            if debrief_count > 0:
                status_text += f"• {debrief_count} game(s) in debrief right now\n"
            if joinable_lobbies:
                status_text += f"• {len(joinable_lobbies)} joinable lobby(ies) with 3+ players right now\n"
            if not status_text:
                ptb_text = " (PTB servers)" if ptb_only else ""
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

        @bot.command(name='graph')
        async def show_graph(ctx, *, graph_args: str = "players online"):
            """
            Display a graph of data over the last week.
            
            Usage: !graph [value]
            Examples:
                !graph players online
                !graph servers
                !graph lobbies
                !graph games in progress
            """
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            from nebulous_bot.models import PlayerSnapshot
            from nebulous_bot.graph_generator import GraphGenerator
            from django.utils import timezone as django_timezone
            from datetime import timedelta
            from asgiref.sync import sync_to_async
            import discord
            
            # Parse the graph type from arguments
            field_name, display_name = GraphGenerator.parse_graph_type(graph_args)
            
            @sync_to_async
            def get_graph_data():
                # Get data from the last 7 days
                now = django_timezone.now()
                week_ago = now - timedelta(days=7)
                
                # Query PlayerSnapshot for the last week
                snapshots = PlayerSnapshot.objects.filter(
                    timestamp__gte=week_ago
                ).order_by('timestamp')
                
                # Extract data points for the requested field
                data_points = []
                for snapshot in snapshots:
                    value = getattr(snapshot, field_name, 0)
                    data_points.append((snapshot.timestamp, float(value)))
                
                return data_points, field_name, display_name
            
            # Show loading message
            loading_msg = await ctx.send("📊 Generating graph...")
            
            try:
                # Get data and generate graph
                data_points, field_name, display_name = await get_graph_data()
                
                # Generate graph image (this is CPU-intensive, run in thread pool)
                def generate_graph():
                    return GraphGenerator.generate_graph_image(data_points, field_name, display_name)
                
                # Run graph generation in executor to avoid blocking
                import concurrent.futures
                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    graph_bytes = await loop.run_in_executor(executor, generate_graph)
                
                # Create file object from bytes
                graph_file = discord.File(
                    io.BytesIO(graph_bytes),
                    filename=f'{display_name.lower().replace(" ", "_")}_graph.png'
                )
                
                # Create embed with graph
                embed = discord.Embed(
                    title=f"📊 {display_name} - Last 7 Days",
                    description=f"Showing {len(data_points)} data points from the past week",
                    color=Config.EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )
                
                if data_points:
                    # Add statistics
                    values = [point[1] for point in data_points]
                    avg_value = sum(values) / len(values) if values else 0
                    max_value = max(values) if values else 0
                    min_value = min(values) if values else 0
                    
                    embed.add_field(
                        name="📈 Statistics",
                        value=(
                            f"**Average:** {avg_value:.1f}\n"
                            f"**Maximum:** {max_value:.0f}\n"
                            f"**Minimum:** {min_value:.0f}"
                        ),
                        inline=True
                    )
                
                embed.set_image(url=f"attachment://{graph_file.filename}")
                embed.set_footer(text="Data from PlayerSnapshot records (5-minute intervals)")
                
                # Delete loading message and send graph
                await loading_msg.delete()
                await ctx.send(embed=embed, file=graph_file)
                
            except Exception as e:
                logger.error(f"Error generating graph: {e}", exc_info=True)
                await loading_msg.edit(
                    content=f"❌ Failed to generate graph: {str(e)}"
                )
        
        @bot.command(name='commandlogs', aliases=['cmdlogs', 'logs'])
        async def show_command_logs(ctx, limit: int = 20, command_filter: str = None):
            """
            View command usage logs (admin/debugging only)
            
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
        
        @bot.event
        async def on_command_error(ctx, error):
            """Handle command errors"""
            if isinstance(error, commands.CommandNotFound):
                return  # Ignore unknown commands
            
            logger.error(f"Command error in {ctx.command}: {error}")
            
            embed = discord.Embed(
                title="❌ Command Error",
                description=f"An error occurred: {str(error)}",
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


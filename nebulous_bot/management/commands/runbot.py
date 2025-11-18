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
from django.core.management.base import BaseCommand

from nebulous_bot.config import Config
from nebulous_bot.server_monitor import ServerMonitor
from nebulous_bot.server_formatter import ServerFormatter
from nebulous_bot.models import BotStatus

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
        
        # Global variables
        server_monitor = None
        formatter = None
        ssl_context = None
        connector = None
        
        @bot.event
        async def on_ready():
            """Called when the bot is ready"""
            nonlocal server_monitor, formatter
            
            logger.info(f'{bot.user} has connected to Discord!')
            logger.info(f'Bot is in {len(bot.guilds)} guilds')
            self.stdout.write(self.style.SUCCESS(f'✅ Bot connected as {bot.user}'))
            
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
            if filter_args:
                args = filter_args.lower().split()
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
            
            # Get filtered servers
            if filters:
                servers = server_monitor.get_servers_by_criteria(**filters)
                title_suffix = f" (Filtered: {filter_args})"
            else:
                servers = server_monitor.cached_servers
                title_suffix = ""
            
            title = f"🚀 {Config.GAME_NAME} - Active Servers{title_suffix}"
            description = f"Found {len(servers)} servers" if servers else "No servers match your criteria."
            embed = formatter.create_server_list_embed(
                servers, title, description, max_servers=15, 
                last_update=server_monitor.last_update, 
                game_start_times=server_monitor.game_start_times
            )
            
            embed.set_footer(text="Filters: open, lobby, ingame, us, eu, competitive, casual • Use !openlobbies for joinable servers")
            message = await ctx.send(embed=embed)
            server_monitor.track_message(message)

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
            server_monitor.track_message(message)

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
                    "`!refresh` - Force update\n"
                    "`!status` - This message"
                ),
                inline=False
            )
            
            embed.set_footer(text="Bot running smoothly! (Django + Azure)")
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
            
            @sync_to_async
            def get_statistics():
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
                
                # Top 3 maps
                top_maps = games.values('map_name').annotate(
                    count=Count('id')
                ).order_by('-count')[:3]
                
                return {
                    'total_games': total_games,
                    'stats': stats,
                    'player_stats': player_stats,
                    'max_players': max_players,
                    'recent_snapshot': recent_snapshot,
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
            
            # Game statistics
            avg_duration_mins = int(result['stats']['avg_duration'] / 60) if result['stats']['avg_duration'] else 0
            total_duration_hours = int(result['stats']['total_duration'] / 3600) if result['stats']['total_duration'] else 0
            
            embed.add_field(
                name="🎮 Games Played",
                value=(
                    f"**Total Games:** {result['total_games']:,}\n"
                    f"**Avg Duration:** {avg_duration_mins} minutes\n"
                    f"**Total Playtime:** {total_duration_hours:,} hours"
                ),
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
            
            embed.set_footer(text="Use !mapstats for detailed map statistics • !serverstats for server statistics")
            await ctx.send(embed=embed)

        @bot.command(name='mapstats', aliases=['maps'])
        async def show_map_statistics(ctx, limit: int = 10):
            """Show map play frequency statistics"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            from nebulous_bot.models import MapStatistics
            from asgiref.sync import sync_to_async
            
            @sync_to_async
            def get_map_stats():
                return list(MapStatistics.objects.filter(
                    total_valid_games__gt=0
                ).order_by('-total_valid_games')[:limit])
            
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
                avg_duration_mins = int(map_stat.avg_game_duration / 60) if map_stat.avg_game_duration else 0
                last_played_text = f"<t:{int(map_stat.last_played.timestamp())}:R>" if map_stat.last_played else "Never"
                
                embed.add_field(
                    name=f"{i}. {map_stat.map_name}",
                    value=(
                        f"**Games:** {map_stat.total_valid_games}\n"
                        f"**Avg Duration:** {avg_duration_mins}m\n"
                        f"**Avg Players:** {map_stat.avg_players_per_game:.1f}\n"
                        f"**Last Played:** {last_played_text}"
                    ),
                    inline=True
                )
            
            embed.set_footer(text="Only valid games (5+ minutes) are counted")
            await ctx.send(embed=embed)

        @bot.command(name='serverstats', aliases=['serverinfo'])
        async def show_server_statistics(ctx, limit: int = 10):
            """Show server usage statistics"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            from nebulous_bot.models import ServerStatistics
            from asgiref.sync import sync_to_async
            
            @sync_to_async
            def get_server_stats():
                return list(ServerStatistics.objects.filter(
                    total_valid_games__gt=0
                ).order_by('-total_valid_games')[:limit])
            
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
                last_game_text = f"<t:{int(srv_stat.last_game_date.timestamp())}:R>" if srv_stat.last_game_date else "Never"
                player_hours = int(srv_stat.total_player_minutes / 60) if srv_stat.total_player_minutes else 0
                
                # Truncate long server names
                server_name = srv_stat.server_name[:40] + "..." if len(srv_stat.server_name) > 40 else srv_stat.server_name
                
                embed.add_field(
                    name=f"{i}. {server_name}",
                    value=(
                        f"**Games:** {srv_stat.total_valid_games}\n"
                        f"**Avg Players:** {srv_stat.avg_players_per_game:.1f}\n"
                        f"**Player-Hours:** {player_hours:,}\n"
                        f"**Last Game:** {last_game_text}"
                    ),
                    inline=True
                )
            
            embed.set_footer(text="Only valid games (5+ minutes) are counted")
            await ctx.send(embed=embed)

        @bot.command(name='updatestats', aliases=['refreshstats'])
        @commands.has_permissions(administrator=True)
        async def force_update_statistics(ctx):
            """Force update statistics aggregation (Admin only)"""
            if not server_monitor:
                await ctx.send("❌ Server monitoring not initialized yet.")
                return
            
            update_msg = await ctx.send("🔄 Updating statistics...")
            
            try:
                from asgiref.sync import sync_to_async
                
                @sync_to_async
                def update_stats():
                    server_monitor.statistics_service.force_aggregation()
                
                await update_stats()
                
                embed = discord.Embed(
                    title="✅ Statistics Updated",
                    description="All statistics have been recalculated from game data.",
                    color=Config.EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )
                await update_msg.edit(content="", embed=embed)
            except Exception as e:
                logger.error(f"Error updating statistics: {e}")
                await update_msg.edit(content="❌ Failed to update statistics. Check logs for details.")

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


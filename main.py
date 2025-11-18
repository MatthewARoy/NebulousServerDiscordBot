import discord
from discord.ext import commands
import logging
import asyncio
import ssl
import certifi
import aiohttp
from datetime import datetime
from typing import List

from nebulous_bot.config import Config
from nebulous_bot.server_monitor import ServerMonitor
from nebulous_bot.server_formatter import ServerFormatter

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('nebulous_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# SSL Configuration for Discord
def create_ssl_context():
    """Create SSL context for Discord connections"""
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return ssl_context

# Bot setup  
intents = discord.Intents.default()
intents.message_content = True

# Global variables for connector (will be created later)
ssl_context = None
connector = None

# Create bot without connector for now
bot = commands.Bot(
    command_prefix=Config.COMMAND_PREFIX, 
    intents=intents
)

# Initialize server monitor and formatter
server_monitor = None
formatter = None

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    global server_monitor, formatter
    
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guilds')
    
    # Validate configuration
    try:
        Config.validate()
        logger.info("Configuration validated successfully")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        await bot.close()
        return
    
    # Initialize and start server monitoring ONLY if not already initialized
    # This prevents duplicate monitoring loops when on_ready() fires multiple times
    if server_monitor is None:
        logger.info("Initializing server monitor for the first time")
        server_monitor = ServerMonitor(bot)
        
        # Initialize formatter - no circular dependency now
        formatter = ServerFormatter()
        
        # Provide formatter to server monitor to avoid duplicate instances
        server_monitor.set_formatter(formatter)
        
        # Start monitoring after formatter is set
        await server_monitor.start_monitoring()
    else:
        logger.info("Bot reconnected - server monitor already initialized")
    
    # Set bot activity (this can be updated on each reconnect)
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name=f"{Config.GAME_NAME} servers"
    )
    await bot.change_presence(activity=activity)

@bot.event
async def on_disconnect():
    """Called when the bot disconnects"""
    global server_monitor
    if server_monitor:
        await server_monitor.stop_monitoring()

@bot.command(name='listservers', aliases=['ls', 'servers'])
async def list_servers(ctx, *, filter_args: str = ""):
    """
    List all active servers with optional filtering
    
    Usage: !listservers [filter]
    Filters: open, lobby, ingame, us, eu, competitive, casual
    Examples: !listservers open, !listservers lobby us
    """
    if not server_monitor or not formatter:
        await ctx.send("❌ Server monitoring not initialized yet. Please wait a moment.")
        return
    
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
    embed = formatter.create_server_list_embed(servers, title, description, max_servers=15, 
                                              last_update=server_monitor.last_update, 
                                              game_start_times=server_monitor.game_start_times)
    
    # Add filter help
    embed.set_footer(text="Filters: open, lobby, ingame, us, eu, competitive, casual • Use !openlobbies for joinable servers")
    message = await ctx.send(embed=embed)
    
    # Track this message for automatic updates
    server_monitor.track_message(message)

@bot.command(name='openlobbies', aliases=['open', 'available'])
async def open_lobbies(ctx):
    """List servers with available player slots"""
    if not server_monitor or not formatter:
        await ctx.send("❌ Server monitoring not initialized yet. Please wait a moment.")
        return
    
    open_servers = server_monitor.get_open_lobbies()
    
    embed = formatter.create_lobby_list_embed(open_servers, server_monitor.last_update)
    message = await ctx.send(embed=embed)
    
    # Track this message for automatic updates
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
        embed = discord.Embed(
            title="✅ Server List Refreshed",
            description=f"Updated {len(server_monitor.cached_servers)} servers",
            color=Config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        await refresh_msg.edit(content="", embed=embed)
    except Exception as e:
        logger.error(f"Error refreshing servers: {e}")
        await refresh_msg.edit(content="❌ Failed to refresh server list. Check logs for details.")

@bot.command(name='status', aliases=['info'])
async def bot_status(ctx):
    """Show bot status and information"""
    embed = discord.Embed(
        title="🤖 Nebulous Server Bot Status",
        color=Config.EMBED_COLOR,
        timestamp=datetime.now()
    )
    
    if server_monitor:
        last_update = server_monitor.last_update
        server_count = len(server_monitor.cached_servers)
        
        embed.add_field(
            name="📊 Server Monitoring",
            value=f"**Active:** ✅\n**Servers Tracked:** {server_count}\n**Update Interval:** {Config.UPDATE_INTERVAL}s",
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
    
    embed.set_footer(text="Bot running smoothly!")
    await ctx.send(embed=embed)

@bot.command(name='stats', aliases=['statistics'])
async def show_statistics(ctx, timeframe: str = "all"):
    """
    Show general game statistics
    
    Usage: !stats [timeframe]
    Timeframes: all, today, week, month
    """
    if not server_monitor:
        await ctx.send("❌ Server monitoring not initialized yet.")
        return
    
    # Import here to avoid circular imports
    from nebulous_bot.models import GameSession, PlayerSnapshot
    from django.db.models import Count, Avg, Sum
    from django.utils import timezone
    from datetime import timedelta
    
    # Calculate timeframe
    now = timezone.now()
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
        embed = discord.Embed(
            title=f"📊 Game Statistics - {timeframe_text}",
            description="No game data available yet. Games are tracked once they complete (5+ minutes).",
            color=Config.EMBED_COLOR_NO_SERVERS
        )
        await ctx.send(embed=embed)
        return
    
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
        avg_players=Avg('total_players'),
        max_players=Sum('total_players')  # We'll get max separately
    )
    
    # Get actual max
    max_players_snapshot = player_snapshots.order_by('-total_players').first()
    max_players = max_players_snapshot.total_players if max_players_snapshot else 0
    
    # Get most recent snapshot for current stats
    recent_snapshot = PlayerSnapshot.objects.order_by('-timestamp').first()
    
    # Create embed
    embed = discord.Embed(
        title=f"📊 Game Statistics - {timeframe_text}",
        color=Config.EMBED_COLOR,
        timestamp=datetime.now()
    )
    
    # Game statistics
    avg_duration_mins = int(stats['avg_duration'] / 60) if stats['avg_duration'] else 0
    total_duration_hours = int(stats['total_duration'] / 3600) if stats['total_duration'] else 0
    
    embed.add_field(
        name="🎮 Games Played",
        value=(
            f"**Total Games:** {total_games:,}\n"
            f"**Avg Duration:** {avg_duration_mins} minutes\n"
            f"**Total Playtime:** {total_duration_hours:,} hours"
        ),
        inline=True
    )
    
    # Player statistics
    avg_players = player_stats['avg_players'] or 0
    embed.add_field(
        name="👥 Player Activity",
        value=(
            f"**Avg Players Online:** {avg_players:.1f}\n"
            f"**Peak Players:** {max_players}\n"
            f"**Avg Players/Game:** {stats['avg_players']:.1f}" if stats['avg_players'] else "N/A"
        ),
        inline=True
    )
    
    # Current stats
    if recent_snapshot:
        embed.add_field(
            name="📈 Current Status",
            value=(
                f"**Players Online:** {recent_snapshot.total_players}\n"
                f"**Active Servers:** {recent_snapshot.total_servers}\n"
                f"**Games In Progress:** {recent_snapshot.games_in_progress}"
            ),
            inline=True
        )
    
    # Top 3 maps
    top_maps = games.values('map_name').annotate(
        count=Count('id')
    ).order_by('-count')[:3]
    
    if top_maps:
        map_text = "\n".join([
            f"**{i+1}.** {m['map_name']}: {m['count']} games"
            for i, m in enumerate(top_maps)
        ])
        embed.add_field(
            name="🗺️ Most Played Maps",
            value=map_text,
            inline=False
        )
    
    embed.set_footer(text=f"Use !mapstats for detailed map statistics • !serverstats for server statistics")
    await ctx.send(embed=embed)

@bot.command(name='mapstats', aliases=['maps'])
async def show_map_statistics(ctx, limit: int = 10):
    """
    Show map play frequency statistics
    
    Usage: !mapstats [limit]
    """
    if not server_monitor:
        await ctx.send("❌ Server monitoring not initialized yet.")
        return
    
    from nebulous_bot.models import MapStatistics
    
    # Get map statistics
    map_stats = MapStatistics.objects.filter(total_valid_games__gt=0).order_by('-total_valid_games')[:limit]
    
    if not map_stats.exists():
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
        timestamp=datetime.now()
    )
    
    # Create a table-like display
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
    """
    Show server usage statistics
    
    Usage: !serverstats [limit]
    """
    if not server_monitor:
        await ctx.send("❌ Server monitoring not initialized yet.")
        return
    
    from nebulous_bot.models import ServerStatistics
    
    # Get server statistics
    server_stats = ServerStatistics.objects.filter(total_valid_games__gt=0).order_by('-total_valid_games')[:limit]
    
    if not server_stats.exists():
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
        timestamp=datetime.now()
    )
    
    # Create a table-like display
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
        # Force statistics aggregation
        server_monitor.statistics_service.force_aggregation()
        
        embed = discord.Embed(
            title="✅ Statistics Updated",
            description="All statistics have been recalculated from game data.",
            color=Config.EMBED_COLOR,
            timestamp=datetime.now()
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
    global ssl_context, connector
    
    try:
        # Create SSL connector inside the event loop
        ssl_context = create_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        # Set the connector for the bot's HTTP client
        bot.http.connector = connector
        
        await bot.start(Config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        await bot.close()
        if connector:
            await connector.close()

def main():
    """Entry point for running the bot with proper event loop setup"""
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == "__main__":
    main() 
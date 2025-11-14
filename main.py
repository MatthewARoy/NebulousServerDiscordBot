import discord
from discord.ext import commands
import logging
import asyncio
import ssl
import certifi
import aiohttp
from datetime import datetime
from typing import List

from config import Config
from server_monitor import ServerMonitor
from server_formatter import ServerFormatter

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
    await ctx.send(embed=embed)

@bot.command(name='openlobbies', aliases=['open', 'available'])
async def open_lobbies(ctx):
    """List servers with available player slots"""
    if not server_monitor or not formatter:
        await ctx.send("❌ Server monitoring not initialized yet. Please wait a moment.")
        return
    
    open_servers = server_monitor.get_open_lobbies()
    
    embed = formatter.create_lobby_list_embed(open_servers, server_monitor.last_update)
    await ctx.send(embed=embed)

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
        value="`!listservers` - List all servers\n`!openlobbies` - Show available servers\n`!refresh` - Force update\n`!status` - This message",
        inline=False
    )
    
    embed.set_footer(text="Bot running smoothly!")
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
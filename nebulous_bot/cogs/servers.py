"""Server listing commands: !listservers, !openlobbies, !refresh.

Command bodies are moved verbatim from runbot.py, except the !listservers
filter-argument parsing, which is extracted into the pure
``parse_listservers_filters`` below so it can be unit-tested
(the one allowed refactor in the cog-split plan).
"""
import discord
from discord.ext import commands
import logging
from datetime import datetime, timezone
from typing import NamedTuple

from nebulous_bot.config import Config
from nebulous_bot.models import BotStatus

logger = logging.getLogger('nebulous_bot')


class ListserversFilters(NamedTuple):
    filters: dict
    show_all: bool
    ptb_only: bool


def parse_listservers_filters(filter_args: str) -> ListserversFilters:
    """Parse the free-text filter argument of !listservers.

    Logic is unchanged from the inline version: unknown tokens are ignored,
    and when both 'lobby' and 'ingame' appear the later check wins
    ('ingame' overwrites 'lobby'), same for 'us'/'eu' ('eu' wins) and
    'competitive'/'casual' ('casual' wins).
    """
    filters = {}
    show_all = False
    ptb_only = False
    if filter_args:
        args = filter_args.lower().split()
        if 'ptb' in args:
            ptb_only = True
            args = [arg for arg in args if arg != 'ptb']
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
    return ListserversFilters(filters, show_all, ptb_only)


class ServersCog(commands.Cog, name='Servers'):
    """Live server listing and refresh commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='listservers', aliases=['ls', 'servers'])
    @commands.cooldown(1, 15, commands.BucketType.channel)
    async def list_servers(self, ctx, *, filter_args: str = ""):
        """
        List all active servers with optional filtering

        Usage: !listservers [filter]
        Filters: ptb, open, lobby, ingame, us, eu, competitive, casual, all
        Examples: !listservers ptb, !listservers open, !listservers lobby us, !listservers all
        """
        server_monitor = self.bot.server_monitor
        formatter = self.bot.formatter
        if not server_monitor or not formatter:
            await ctx.send("❌ Server monitoring not initialized yet. Please wait a moment.")
            return

        # Always fetch fresh data from Steam
        await server_monitor.force_update()

        # Parse filter arguments
        filters, show_all, ptb_only = parse_listservers_filters(filter_args)

        servers = server_monitor.get_servers_for_listservers(ptb_only, show_all, filters)
        if filters:
            title_suffix = f" (Filtered: {filter_args})"
        else:
            if ptb_only and not show_all:
                title_suffix = " (PTB Servers)"
            elif show_all:
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
        footer_text = "Filters: ptb, open, lobby, ingame, us, eu, competitive, casual, all • Use !openlobbies for joinable servers"
        embed.set_footer(text=footer_text)
        message = await ctx.send(embed=embed)
        metadata = {
            'command': 'listservers',
            'filters': dict(filters),
            'ptb_only': ptb_only,
            'show_all': show_all
        }
        await server_monitor.track_message(message, metadata=metadata)

    @commands.command(name='openlobbies', aliases=['open', 'available'])
    @commands.cooldown(1, 15, commands.BucketType.channel)
    async def open_lobbies(self, ctx):
        """List servers with available player slots"""
        server_monitor = self.bot.server_monitor
        formatter = self.bot.formatter
        if not server_monitor or not formatter:
            await ctx.send("❌ Server monitoring not initialized yet. Please wait a moment.")
            return

        # Always fetch fresh data from Steam
        await server_monitor.force_update()

        open_servers = server_monitor.get_open_lobbies()
        embed = formatter.create_lobby_list_embed(open_servers, server_monitor.last_update)
        message = await ctx.send(embed=embed)
        await server_monitor.track_message(message)

    @commands.command(name='refresh', aliases=['update'])
    @commands.cooldown(1, 30, commands.BucketType.channel)
    async def refresh_servers(self, ctx):
        """Force refresh the server list"""
        server_monitor = self.bot.server_monitor
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

"""Next-game waitlist commands: !nextgame, !cancelnextgame.

Command bodies are moved verbatim from runbot.py, except the !nextgame
argument parsing, which is extracted into the pure ``parse_nextgame_args``
below so it can be unit-tested (part of the one allowed refactor in the
cog-split plan). Waiter keys are (user_id, ptb_only, modded_only, ...)
tuples managed by ServerMonitor — one user can wait in several queue
modes at once.
"""
import discord
from discord.ext import commands
import logging
from datetime import datetime, timezone
from typing import NamedTuple

from nebulous_bot.config import Config

logger = logging.getLogger('nebulous_bot')


class NextgameArgs(NamedTuple):
    ptb_only: bool
    modded_only: bool
    newplayer_only: bool
    lobby_only: bool
    skip_current_lobbies: bool


def parse_nextgame_args(args: str) -> NextgameArgs:
    """Parse the free-text arguments of !nextgame.

    Logic is unchanged from the inline version: tokens are matched
    case-insensitively, unknown tokens are ignored.
    """
    args_lower = args.lower().strip()
    tokens = [token for token in args_lower.split() if token]
    ptb_only = any(token == 'ptb' for token in tokens)
    modded_only = any(token in ('modded', 'mod', 'mfc') for token in tokens)
    newplayer_only = any(token in ('newplayer', 'new-player', 'np', 'beginner') for token in tokens)
    lobby_only = any(token in ('lobby', '--lobby', '-l') for token in tokens)
    skip_current_lobbies = any(token in ('--skip', '-skip', '-s', 'skip') for token in tokens)
    return NextgameArgs(ptb_only, modded_only, newplayer_only, lobby_only, skip_current_lobbies)


class NextGameCog(commands.Cog, name='Next Game'):
    """Waitlist notifications for the next joinable game."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='nextgame', aliases=['notify', 'notifyme', 'ng'])
    @commands.cooldown(2, 30, commands.BucketType.user)
    async def next_game_notify(self, ctx, *, args: str = ""):
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
        server_monitor = self.bot.server_monitor
        if not server_monitor:
            await ctx.send("❌ Server monitoring not initialized yet.")
            return

        user_id = ctx.author.id
        channel_id = ctx.channel.id
        username = str(ctx.author)

        # Parse arguments
        ptb_only, modded_only, newplayer_only, lobby_only, skip_current_lobbies = parse_nextgame_args(args)

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

        # The skip-current-lobbies snapshot below needs recent data, but the
        # monitoring loop's cache already is recent — only sweep if it isn't.
        await server_monitor.ensure_fresh()

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

    @commands.command(name='cancelnextgame', aliases=['nextgamecancel'])
    async def cancel_next_game_notify(self, ctx):
        """Cancel your next game notification"""
        server_monitor = self.bot.server_monitor
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

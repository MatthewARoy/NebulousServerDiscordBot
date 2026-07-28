"""Statistics commands: !stats, !mapstats, !serverstats, !graph.

Pure ORM reads (via sync_to_async) plus matplotlib graph generation.
Command bodies are moved verbatim from runbot.py; each method rebinds
``server_monitor = self.bot.server_monitor`` so the original None-guards
and wording stay identical.
"""
import discord
from discord.ext import commands
import logging
import asyncio
import io
from datetime import datetime, timezone

from nebulous_bot.config import Config

logger = logging.getLogger('nebulous_bot')


class StatsCog(commands.Cog, name='Statistics'):
    """Game, map, and server statistics computed live from GameSession."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='stats', aliases=['statistics'])
    async def show_statistics(self, ctx, timeframe: str = "all"):
        """Show general game statistics"""
        server_monitor = self.bot.server_monitor
        if not server_monitor:
            await ctx.send("❌ Server monitoring not initialized yet.")
            return

        from nebulous_bot.models import GameSession, PlayerSnapshot
        from django.db.models import Count, Avg, Sum
        from django.utils import timezone as django_timezone
        from datetime import timedelta
        from asgiref.sync import sync_to_async
        from zoneinfo import ZoneInfo

        # Pacific timezone for consistent display
        pst = ZoneInfo('America/Los_Angeles')

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

    @commands.command(name='mapstats', aliases=['maps'])
    async def show_map_statistics(self, ctx, limit: int = 10):
        """Show map play frequency statistics (calculated from games in real-time)"""
        server_monitor = self.bot.server_monitor
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

    @commands.command(name='serverstats', aliases=['serverinfo'])
    async def show_server_statistics(self, ctx, limit: int = 10):
        """Show server usage statistics (calculated from games in real-time)"""
        server_monitor = self.bot.server_monitor
        if not server_monitor:
            await ctx.send("❌ Server monitoring not initialized yet.")
            return

        from nebulous_bot.models import GameSession
        from django.db.models import Count, Avg, Max, Sum, F
        from asgiref.sync import sync_to_async

        @sync_to_async
        def get_server_stats():
            # Group by server_name, not server_id: server_id is the Steam
            # session steamid, which changes on every server-process restart
            # and fragments one server's history across many rows.
            stats = list(GameSession.objects.filter(is_valid_game=True).values('server_name').annotate(
                total_games=Count('id'),
                avg_players=Avg('players_at_start'),
                last_game=Max('game_start'),
                player_seconds=Sum(F('players_at_start') * F('duration_seconds'))
            ).order_by('-total_games')[:limit])

            for stat in stats:
                stat['player_hours'] = (stat['player_seconds'] or 0) / 3600

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

    @commands.command(name='graph')
    @commands.cooldown(1, 15, commands.BucketType.channel)
    async def show_graph(self, ctx, *, graph_args: str = "players online"):
        """
        Display a graph of data over the last week.

        Usage: !graph [value]
        Examples:
            !graph players online
            !graph servers
            !graph lobbies
            !graph games in progress
        """
        server_monitor = self.bot.server_monitor
        if not server_monitor:
            await ctx.send("❌ Server monitoring not initialized yet.")
            return

        from nebulous_bot.models import PlayerSnapshot
        from nebulous_bot.graph_generator import GraphGenerator
        from django.utils import timezone as django_timezone
        from datetime import timedelta
        from asgiref.sync import sync_to_async

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

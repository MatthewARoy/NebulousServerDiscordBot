"""
Statistics tracking service for Nebulous servers.
Handles game session tracking, player snapshots, and statistics aggregation.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from django.utils import timezone as django_timezone

from nebulous_bot.models import (
    GameSession, PlayerSnapshot
)

logger = logging.getLogger(__name__)


class GameSessionTracker:
    """
    Tracks game sessions across servers.
    Monitors state transitions and records completed games.
    Recovers ongoing games from database on bot restart.
    """
    
    def __init__(self):
        # Track ongoing game sessions in memory
        # Format: {server_id: game_session_id}
        self.active_sessions = {}
        # Tracked servers currently without people, or missing from the
        # listing, and the poll that first found them that way.
        # Format: {server_id: datetime}
        self._unoccupied_since = {}
        # Servers reattached at startup and not yet seen with people. Nothing
        # observed says when (or whether) their game ended.
        self._unconfirmed = set()
        # Recovery is deferred to the first update() call: __init__ runs
        # inside async on_ready, where Django's ORM raises
        # SynchronousOnlyOperation. update() runs in an executor thread.
        self._recovery_pending = True

    def ensure_recovered(self):
        """Run ongoing-game recovery once, from a sync (executor) context."""
        if self._recovery_pending:
            self._recovery_pending = False
            self._recover_ongoing_games()

    # Sessions older than this cannot plausibly still be running (games are
    # well under an hour); close them as invalid instead of reattaching.
    STALE_RECOVERY_AGE = timedelta(hours=6)

    # How long a tracked server may stay empty or unlisted before its game is
    # treated as over. A lone player reconnecting or a brief listing dropout
    # must not split one game into two rows. The game's end is backdated to
    # when the server was first found that way, so this costs no accuracy.
    ABANDON_GRACE = timedelta(minutes=5)

    def _recover_ongoing_games(self):
        """
        Recover ongoing games from database on bot restart.
        This allows us to continue tracking games that started before the bot restarted.

        Stale rows are closed first: recovery was broken for months (item
        #28), so restarts and vanished servers left hundreds of rows with
        is_ongoing=True. Reattaching those would finalize them with
        months-long durations and poison the statistics.
        """
        try:
            cutoff = django_timezone.now() - self.STALE_RECOVERY_AGE
            stale_count = GameSession.objects.filter(
                is_ongoing=True, game_start__lt=cutoff
            ).update(is_ongoing=False, is_valid_game=False)
            if stale_count:
                logger.info(f"Closed {stale_count} stale ongoing session(s) older than {self.STALE_RECOVERY_AGE}")

            ongoing_games = list(GameSession.objects.filter(is_ongoing=True))
            recovered_count = 0
            
            for game in ongoing_games:
                self.active_sessions[game.server_id] = game.id
                self._unconfirmed.add(game.server_id)
                recovered_count += 1
            
            if recovered_count > 0:
                logger.info(f"Recovered {recovered_count} ongoing game(s) from database")
            else:
                logger.info("No ongoing games to recover")
                
        except Exception as e:
            logger.error(f"Error recovering ongoing games: {e}", exc_info=True)
    
    def observe(self, servers: List[Dict], all_servers: List[Dict]):
        """
        Process one sweep of the server list.

        Only servers on the display-filtered list can start a session, so the
        statistics keep covering public games. A session that has started is
        followed on the unfiltered list until its game really ends: the filter
        also hides a server the moment its last player leaves, which is
        exactly when the end of the game has to be seen.

        Servers that are neither filtered-in nor tracked cost one set lookup
        and no database work.

        Args:
            servers: Display-filtered server states
            all_servers: Every listed server
        """
        startable = {self._server_key(server) for server in servers}
        listed = set()
        for server in all_servers:
            server_id = self._server_key(server)
            listed.add(server_id)
            if server_id not in startable and server_id not in self.active_sessions:
                continue
            try:
                self.update_server_state(server, may_start=server_id in startable)
            except Exception as e:
                logger.error(f"Error tracking game session for {server.get('name')}: {e}", exc_info=True)

        self._close_abandoned_sessions(listed)

    @staticmethod
    def _server_key(server: Dict) -> str:
        return server.get('id', server.get('address', ''))

    def _stop_tracking(self, server_id: str):
        self.active_sessions.pop(server_id, None)
        self._unoccupied_since.pop(server_id, None)
        self._unconfirmed.discard(server_id)

    def _close_abandoned_sessions(self, listed_ids: set):
        """Close sessions whose server has been empty or unlisted past the grace period."""
        now = django_timezone.now()
        for server_id, session_id in list(self.active_sessions.items()):
            if server_id not in listed_ids:
                self._unoccupied_since.setdefault(server_id, now)
            left_at = self._unoccupied_since.get(server_id)
            if left_at is None or now - left_at < self.ABANDON_GRACE:
                continue
            try:
                self._close_abandoned_session(server_id, session_id, left_at)
            except Exception as e:
                logger.error(f"Error closing abandoned game #{session_id}: {e}", exc_info=True)

    def _close_abandoned_session(self, server_id: str, session_id: int, left_at: datetime):
        if server_id in self._unconfirmed:
            # Same call as the startup stale close: with no observed end, a
            # duration would only measure how long the bot was away.
            GameSession.objects.filter(id=session_id).update(is_ongoing=False, is_valid_game=False)
            logger.info(f"Closed recovered game #{session_id} as invalid: its server never reappeared with players")
        else:
            game_session = GameSession.objects.filter(id=session_id).first()
            if game_session:
                self._finalize_game_session(game_session, {}, left_at)
        self._stop_tracking(server_id)

    def update_server_state(self, server: Dict, may_start: bool = True) -> Optional[GameSession]:
        """
        Update tracking for a server based on its current state.
        Returns a GameSession object if a game was completed.

        Args:
            server: Server dictionary with current state information
            may_start: Whether an in_game state here may open a new session

        Returns:
            GameSession if a game was completed, None otherwise
        """
        server_id = self._server_key(server)
        if not server_id:
            return None

        current_time = django_timezone.now()
        occupied = human_players(server) > 0
        left_at = self._unoccupied_since.get(server_id)
        tracked = server_id in self.active_sessions

        # The player count does not depend on the rules answer checked below,
        # so a server with people keeps its session through an A2S outage.
        if tracked:
            if occupied:
                self._unoccupied_since.pop(server_id, None)
                self._unconfirmed.discard(server_id)
            elif left_at is None:
                self._unoccupied_since[server_id] = current_time

        # Without an A2S rules answer `status` falls back to 'lobby', which
        # this state machine would read as "the game ended" and then, on the
        # next successful sweep, as "a new game started" — splitting one real
        # game into two rows. Hold the existing session instead.
        if not server.get('status_known', True):
            return None

        current_status = server.get('status', 'lobby')

        # An empty server adds nothing until the grace period decides, except
        # a lobby, which is a definite end. A recovered session has no time
        # to backdate that end to, so it waits for the grace period as well.
        if tracked and not occupied and (current_status != 'lobby' or server_id in self._unconfirmed):
            return None

        # When people return after a gap, the game ended when the gap began.
        end_time = left_at or current_time

        # Check if we have an ongoing game for this server
        game_session_id = self.active_sessions.get(server_id)
        game_session = None
        
        if game_session_id:
            try:
                game_session = GameSession.objects.get(id=game_session_id)
            except GameSession.DoesNotExist:
                # Game was deleted, clean up
                self._stop_tracking(server_id)
                game_session = None
        
        completed_game = None
        
        # Handle different statuses
        if current_status == 'lobby':
            if game_session:
                # Game ended (went back to lobby), finalize it
                completed_game = self._finalize_game_session(game_session, server, end_time)
                self._stop_tracking(server_id)
            # No action needed for lobby state

        elif current_status == 'in_game':
            if game_session and game_session.game_end:
                # Debrief straight to in_game: the lobby fell between polls.
                # This is a new game, not more of the one that already ended.
                completed_game = self._finalize_game_session(game_session, server, current_time)
                self._stop_tracking(server_id)
                game_session = None

            if not game_session:
                if may_start:
                    # New game starting!
                    game_session = self._create_game_session(server, current_time)
                    self.active_sessions[server_id] = game_session.id
                    logger.info(
                        f"Game #{game_session.id} started on '{server.get('name')}': "
                        f"{server.get('map')} with {server.get('players')} players"
                    )
            else:
                # Game ongoing, update max player count
                self._update_max_players(game_session, server)
                
        elif current_status == 'debrief':
            if game_session and game_session.is_ongoing:
                # Game entered debrief, mark end time
                game_session.game_end = end_time
                game_session.players_at_end = human_players(server)
                # Update max players one last time
                current_players = human_players(server)
                if current_players > game_session.max_players_during_game:
                    game_session.max_players_during_game = current_players
                game_session.save()
                logger.info(f"Game #{game_session.id} entered debrief on '{server.get('name')}'")
            # Keep tracking until lobby (don't delete yet)
        
        return completed_game
    
    def _create_game_session(self, server: Dict, start_time: datetime) -> GameSession:
        """
        Create a new game session in the database immediately when game starts.
        Game is saved with unique ID and can be recovered on bot restart.
        """
        game_session = GameSession.objects.create(
            server_id=server.get('id', server.get('address', '')),
            server_name=server.get('name', 'Unknown'),
            server_address=server.get('address', ''),
            map_name=server.get('map', 'Unknown'),
            game_mode=server.get('game_mode', 'Unknown'),
            region=server.get('region', 'Unknown'),
            game_start=start_time,
            players_at_start=server.get('players', 0),
            max_players_during_game=server.get('players', 0),
            competitive=server.get('competitive', False),
            autobalance=server.get('autobalance', False),
            rank_restricted=server.get('rank_restricted', False),
            has_password=server.get('has_password', False),
            is_ongoing=True,  # Mark as ongoing
        )
        
        return game_session
    
    def _finalize_game_session(self, game_session: GameSession, server: Dict, end_time: datetime) -> Optional[GameSession]:
        """
        Finalize a game session when it is known to be over.
        Returns the session if it's valid (5+ minutes), None otherwise.
        """
        # If game_end wasn't set (shouldn't happen with debrief), set it now
        if not game_session.game_end:
            game_session.game_end = end_time
            game_session.players_at_end = human_players(server)

        # Mark as no longer ongoing and calculate duration
        game_session.is_ongoing = False
        game_session.calculate_duration()
        game_session.save()
        
        if game_session.is_valid_game:
            logger.info(
                f"✅ Game #{game_session.id} completed on '{game_session.server_name}': "
                f"{game_session.map_name} - {game_session.duration_seconds}s with {game_session.players_at_start} players"
            )
            return game_session
        else:
            logger.debug(
                f"⏱️ Game #{game_session.id} too short on '{game_session.server_name}': "
                f"{game_session.duration_seconds}s (need 300s minimum)"
            )
            return None
    
    def _update_max_players(self, game_session: GameSession, server: Dict):
        """Update max player count during an ongoing game"""
        current_players = human_players(server)
        if current_players > game_session.max_players_during_game:
            game_session.max_players_during_game = current_players
            game_session.save(update_fields=['max_players_during_game', 'updated_at'])


def human_players(server: Dict) -> int:
    """People on a server. Valve's A2S convention counts bots inside `players`."""
    return max(0, server.get('players', 0) - server.get('bots', 0))


def summarize_servers(servers: List[Dict]) -> Dict[str, int]:
    """Population totals for one snapshot.

    Pass the unfiltered server list. The default display filter hides whole
    servers, so summing over it silently drops every person on a server that
    has a bot or a "private"-style name. Only servers with at least one person
    count toward the server, lobby and game totals.
    """
    populated = [s for s in servers if human_players(s) > 0]
    return {
        'total_players': sum(human_players(s) for s in populated),
        'total_servers': len(populated),
        'open_lobbies': sum(1 for s in populated if s.get('status') == 'lobby'),
        'games_in_progress': sum(1 for s in populated if s.get('status') == 'in_game'),
    }


class PlayerCountTracker:
    """
    Tracks player count snapshots over time.
    """
    
    def __init__(self):
        self.last_snapshot_time = None
        self.snapshot_interval = timedelta(minutes=5)  # Take snapshot every 5 minutes
    
    def should_take_snapshot(self) -> bool:
        """Check if enough time has passed to take a new snapshot"""
        if self.last_snapshot_time is None:
            return True
        
        now = django_timezone.now()
        return (now - self.last_snapshot_time) >= self.snapshot_interval
    
    def take_snapshot(self, servers: List[Dict], steam_concurrent: Optional[int] = None):
        """
        Take a snapshot of current player counts across all servers.

        Args:
            servers: Unfiltered list of server dictionaries
            steam_concurrent: Steam's whole-game player count, None if unknown
        """
        if not self.should_take_snapshot():
            return

        totals = summarize_servers(servers)
        PlayerSnapshot.objects.create(**totals, steam_concurrent=steam_concurrent)

        self.last_snapshot_time = django_timezone.now()
        logger.debug(f"Snapshot taken: {totals['total_players']} players across {totals['total_servers']} servers")


class StatisticsService:
    """
    Main service for statistics tracking.
    Tracks game sessions and player count snapshots in real-time.
    Statistics are calculated directly from GameSession table when needed.
    """
    
    def __init__(self):
        self.game_tracker = GameSessionTracker()
        self.player_tracker = PlayerCountTracker()
    
    def update(
        self,
        servers: List[Dict],
        all_servers: Optional[List[Dict]] = None,
        steam_concurrent: Optional[int] = None,
    ):
        """
        Main update method called from the monitoring loop.

        Args:
            servers: Display-filtered server states, the only ones that can
                start a game session
            all_servers: Every listed server, used to follow started sessions
                and for population snapshots
            steam_concurrent: Steam's whole-game player count, None if unknown
        """
        listed = servers if all_servers is None else all_servers

        # First call after startup: reattach ongoing games from the DB.
        # Safe here (executor thread), unsafe in __init__ (event loop).
        self.game_tracker.ensure_recovered()

        # Track game sessions (saved immediately to database)
        try:
            self.game_tracker.observe(servers, listed)
        except Exception as e:
            logger.error(f"Error tracking game sessions: {e}", exc_info=True)

        # Take player count snapshot if needed (every 5 minutes)
        try:
            self.player_tracker.take_snapshot(listed, steam_concurrent)
        except Exception as e:
            logger.error(f"Error taking player snapshot: {e}", exc_info=True)


"""
Statistics tracking service for Nebulous servers.
Handles game session tracking, player snapshots, and statistics aggregation.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from django.db.models import Count, Avg, Sum, F, Q
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
        self._recover_ongoing_games()
    
    def _recover_ongoing_games(self):
        """
        Recover ongoing games from database on bot restart.
        This allows us to continue tracking games that started before the bot restarted.
        
        Note: This is called from __init__ in a synchronous context,
        but the StatisticsService is instantiated in an async context (the bot startup).
        We use list() to force evaluation of the queryset within the try block,
        avoiding lazy evaluation issues.
        """
        try:
            # Force immediate evaluation with list() to avoid async context issues
            ongoing_games = list(GameSession.objects.filter(is_ongoing=True))
            recovered_count = 0
            
            for game in ongoing_games:
                self.active_sessions[game.server_id] = game.id
                recovered_count += 1
            
            if recovered_count > 0:
                logger.info(f"Recovered {recovered_count} ongoing game(s) from database")
            else:
                logger.info("No ongoing games to recover")
                
        except Exception as e:
            logger.error(f"Error recovering ongoing games: {e}", exc_info=True)
    
    def update_server_state(self, server: Dict) -> Optional[GameSession]:
        """
        Update tracking for a server based on its current state.
        Returns a GameSession object if a game was completed.
        
        Args:
            server: Server dictionary with current state information
            
        Returns:
            GameSession if a game was completed, None otherwise
        """
        server_id = server.get('id', server.get('address', ''))
        if not server_id:
            return None
        
        current_status = server.get('status', 'lobby')
        current_time = django_timezone.now()
        
        # Check if we have an ongoing game for this server
        game_session_id = self.active_sessions.get(server_id)
        game_session = None
        
        if game_session_id:
            try:
                game_session = GameSession.objects.get(id=game_session_id)
            except GameSession.DoesNotExist:
                # Game was deleted, clean up
                del self.active_sessions[server_id]
                game_session = None
        
        completed_game = None
        
        # Handle different statuses
        if current_status == 'lobby':
            if game_session:
                # Game ended (went back to lobby), finalize it
                completed_game = self._finalize_game_session(game_session, server, current_time)
                del self.active_sessions[server_id]
            # No action needed for lobby state
            
        elif current_status == 'in_game':
            if not game_session:
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
                game_session.game_end = current_time
                game_session.players_at_end = server.get('players', 0)
                # Update max players one last time
                current_players = server.get('players', 0)
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
        Finalize a game session when transitioning back to lobby.
        Returns the session if it's valid (5+ minutes), None otherwise.
        """
        # If game_end wasn't set (shouldn't happen with debrief), set it now
        if not game_session.game_end:
            game_session.game_end = end_time
            game_session.players_at_end = server.get('players', 0)
        
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
        current_players = server.get('players', 0)
        if current_players > game_session.max_players_during_game:
            game_session.max_players_during_game = current_players
            game_session.save(update_fields=['max_players_during_game', 'updated_at'])


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
    
    def take_snapshot(self, servers: List[Dict]):
        """
        Take a snapshot of current player counts across all servers.
        
        Args:
            servers: List of server dictionaries
        """
        if not self.should_take_snapshot():
            return
        
        total_players = sum(s.get('players', 0) for s in servers)
        total_servers = len(servers)
        open_lobbies = len([s for s in servers if s.get('status') == 'lobby'])
        games_in_progress = len([s for s in servers if s.get('status') == 'in_game'])
        
        PlayerSnapshot.objects.create(
            total_players=total_players,
            total_servers=total_servers,
            open_lobbies=open_lobbies,
            games_in_progress=games_in_progress
        )
        
        self.last_snapshot_time = django_timezone.now()
        logger.debug(f"Snapshot taken: {total_players} players across {total_servers} servers")


class StatisticsService:
    """
    Main service for statistics tracking.
    Tracks game sessions and player count snapshots in real-time.
    Statistics are calculated directly from GameSession table when needed.
    """
    
    def __init__(self):
        self.game_tracker = GameSessionTracker()
        self.player_tracker = PlayerCountTracker()
    
    def update(self, servers: List[Dict]):
        """
        Main update method called from the monitoring loop.
        
        Args:
            servers: List of current server states
        """
        # Track game sessions (saved immediately to database)
        for server in servers:
            try:
                self.game_tracker.update_server_state(server)
            except Exception as e:
                logger.error(f"Error tracking game session for {server.get('name')}: {e}", exc_info=True)
        
        # Take player count snapshot if needed (every 5 minutes)
        try:
            self.player_tracker.take_snapshot(servers)
        except Exception as e:
            logger.error(f"Error taking player snapshot: {e}", exc_info=True)


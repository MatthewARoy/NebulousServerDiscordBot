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
    GameSession, PlayerSnapshot, ServerStatistics, MapStatistics
)

logger = logging.getLogger(__name__)


class GameSessionTracker:
    """
    Tracks game sessions across servers.
    Monitors state transitions and records completed games.
    """
    
    def __init__(self):
        # Track ongoing game sessions in memory
        # Format: {server_id: {session_data}}
        self.active_sessions = {}
        
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
        
        # Get or create session tracking
        if server_id not in self.active_sessions:
            self.active_sessions[server_id] = {
                'status': current_status,
                'last_update': current_time,
                'lobby_start': None,
                'game_start': None,
                'db_session': None,
                'server_info': self._extract_server_info(server)
            }
            return None
        
        session = self.active_sessions[server_id]
        previous_status = session['status']
        
        # Handle state transitions
        completed_game = None
        
        # Transition: * -> lobby (reset/new lobby)
        if current_status == 'lobby' and previous_status != 'lobby':
            # Check if we have a game session that should be finalized
            if session['db_session'] and previous_status == 'debrief':
                completed_game = self._finalize_game_session(
                    session['db_session'], server, current_time
                )
            
            # Reset for new lobby
            session['status'] = 'lobby'
            session['lobby_start'] = current_time
            session['game_start'] = None
            session['db_session'] = None
            session['server_info'] = self._extract_server_info(server)
            
        # Transition: lobby -> in_game
        elif current_status == 'in_game' and previous_status == 'lobby':
            session['status'] = 'in_game'
            session['game_start'] = current_time
            session['db_session'] = self._create_game_session(server, session, current_time)
            logger.info(f"Game started on {server.get('name')}: {server.get('map')} with {server.get('players')} players")
            
        # Transition: in_game -> debrief
        elif current_status == 'debrief' and previous_status == 'in_game':
            session['status'] = 'debrief'
            if session['db_session']:
                self._update_game_session_debrief(session['db_session'], server, current_time)
                logger.info(f"Game entered debrief on {server.get('name')}")
            
        # Update status if no transition
        else:
            session['status'] = current_status
            session['last_update'] = current_time
            
            # Update max player count during game
            if current_status == 'in_game' and session['db_session']:
                self._update_max_players(session['db_session'], server)
        
        return completed_game
    
    def _extract_server_info(self, server: Dict) -> Dict:
        """Extract relevant server information for tracking"""
        return {
            'server_id': server.get('id', server.get('address', '')),
            'server_name': server.get('name', 'Unknown'),
            'server_address': server.get('address', ''),
            'map_name': server.get('map', 'Unknown'),
            'game_mode': server.get('game_mode', 'Unknown'),
            'region': server.get('region', 'Unknown'),
            'competitive': server.get('competitive', False),
            'autobalance': server.get('autobalance', False),
            'rank_restricted': server.get('rank_restricted', False),
        }
    
    def _create_game_session(self, server: Dict, session: Dict, start_time: datetime) -> GameSession:
        """Create a new game session in the database"""
        info = self._extract_server_info(server)
        
        game_session = GameSession.objects.create(
            server_id=info['server_id'],
            server_name=info['server_name'],
            server_address=info['server_address'],
            map_name=info['map_name'],
            game_mode=info['game_mode'],
            region=info['region'],
            lobby_start=session.get('lobby_start'),
            game_start=start_time,
            players_at_start=server.get('players', 0),
            max_players_during_game=server.get('players', 0),
            competitive=info['competitive'],
            autobalance=info['autobalance'],
            rank_restricted=info['rank_restricted'],
        )
        
        return game_session
    
    def _update_game_session_debrief(self, game_session: GameSession, server: Dict, debrief_time: datetime):
        """Update game session when it enters debrief"""
        game_session.game_end = debrief_time
        game_session.players_at_end = server.get('players', 0)
        
        # Update max players if current is higher
        current_players = server.get('players', 0)
        if current_players > game_session.max_players_during_game:
            game_session.max_players_during_game = current_players
        
        game_session.save()
    
    def _finalize_game_session(self, game_session: GameSession, server: Dict, end_time: datetime) -> Optional[GameSession]:
        """
        Finalize a game session when transitioning back to lobby.
        Returns the session if it's valid (5+ minutes), None otherwise.
        """
        # If game_end wasn't set (shouldn't happen), set it now
        if not game_session.game_end:
            game_session.game_end = end_time
            game_session.players_at_end = server.get('players', 0)
        
        # Calculate duration and validity
        game_session.calculate_duration()
        game_session.save()
        
        if game_session.is_valid_game:
            logger.info(
                f"Valid game completed on {game_session.server_name}: "
                f"{game_session.map_name} ({game_session.duration_seconds}s)"
            )
            return game_session
        else:
            logger.debug(
                f"Game too short on {game_session.server_name}: "
                f"{game_session.duration_seconds}s (need 300s minimum)"
            )
            return None
    
    def _update_max_players(self, game_session: GameSession, server: Dict):
        """Update max player count during a game"""
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


class StatisticsAggregator:
    """
    Aggregates statistics from raw game session data.
    """
    
    @staticmethod
    def update_server_statistics():
        """
        Update aggregated statistics for all servers.
        Should be run periodically (e.g., every hour).
        """
        logger.info("Updating server statistics...")
        
        # Get all servers that have games
        servers_with_games = GameSession.objects.values('server_id', 'server_name').distinct()
        
        for server_info in servers_with_games:
            server_id = server_info['server_id']
            server_name = server_info['server_name']
            
            # Calculate statistics for this server
            games = GameSession.objects.filter(server_id=server_id)
            valid_games = games.filter(is_valid_game=True)
            
            stats = {
                'total_games': games.count(),
                'total_valid_games': valid_games.count(),
            }
            
            if valid_games.exists():
                stats['last_game_date'] = valid_games.first().game_start
                stats['first_game_date'] = valid_games.last().game_start
                stats['avg_players_per_game'] = valid_games.aggregate(
                    avg=Avg('players_at_start')
                )['avg'] or 0.0
                
                # Calculate total player-minutes
                total_player_minutes = 0
                for game in valid_games:
                    if game.duration_seconds:
                        player_minutes = (game.players_at_start * game.duration_seconds) / 60
                        total_player_minutes += player_minutes
                stats['total_player_minutes'] = int(total_player_minutes)
            else:
                stats['last_game_date'] = None
                stats['first_game_date'] = None
                stats['avg_players_per_game'] = 0.0
                stats['total_player_minutes'] = 0
            
            # Update or create server statistics
            ServerStatistics.objects.update_or_create(
                server_id=server_id,
                defaults={
                    'server_name': server_name,
                    **stats
                }
            )
        
        logger.info(f"Updated statistics for {len(servers_with_games)} servers")
    
    @staticmethod
    def update_map_statistics():
        """
        Update aggregated statistics for all maps.
        Should be run periodically (e.g., every hour).
        """
        logger.info("Updating map statistics...")
        
        # Get all maps that have been played
        maps_played = GameSession.objects.values('map_name').distinct()
        
        for map_info in maps_played:
            map_name = map_info['map_name']
            
            # Calculate statistics for this map
            games = GameSession.objects.filter(map_name=map_name)
            valid_games = games.filter(is_valid_game=True)
            
            stats = {
                'total_games': games.count(),
                'total_valid_games': valid_games.count(),
            }
            
            if valid_games.exists():
                stats['last_played'] = valid_games.first().game_start
                
                # Calculate average duration
                avg_duration = valid_games.filter(
                    duration_seconds__isnull=False
                ).aggregate(avg=Avg('duration_seconds'))['avg']
                stats['avg_game_duration'] = avg_duration or 0.0
                
                # Calculate average players
                stats['avg_players_per_game'] = valid_games.aggregate(
                    avg=Avg('players_at_start')
                )['avg'] or 0.0
            else:
                stats['last_played'] = None
                stats['avg_game_duration'] = 0.0
                stats['avg_players_per_game'] = 0.0
            
            # Update or create map statistics
            MapStatistics.objects.update_or_create(
                map_name=map_name,
                defaults=stats
            )
        
        logger.info(f"Updated statistics for {len(maps_played)} maps")
    
    @staticmethod
    def update_all_statistics():
        """Update all aggregated statistics"""
        StatisticsAggregator.update_server_statistics()
        StatisticsAggregator.update_map_statistics()


class StatisticsService:
    """
    Main service for statistics tracking.
    Combines game session tracking, player snapshots, and aggregation.
    """
    
    def __init__(self):
        self.game_tracker = GameSessionTracker()
        self.player_tracker = PlayerCountTracker()
        self.last_aggregation = None
        self.aggregation_interval = timedelta(hours=1)
    
    def update(self, servers: List[Dict]):
        """
        Main update method called from the monitoring loop.
        
        Args:
            servers: List of current server states
        """
        # Track game sessions
        for server in servers:
            try:
                completed_game = self.game_tracker.update_server_state(server)
                if completed_game:
                    # A valid game was completed, trigger statistics update for this server/map
                    # (We do full aggregation periodically, but could optimize here)
                    pass
            except Exception as e:
                logger.error(f"Error tracking game session for {server.get('name')}: {e}", exc_info=True)
        
        # Take player count snapshot if needed
        try:
            self.player_tracker.take_snapshot(servers)
        except Exception as e:
            logger.error(f"Error taking player snapshot: {e}", exc_info=True)
        
        # Update aggregated statistics if needed
        if self._should_aggregate():
            try:
                StatisticsAggregator.update_all_statistics()
                self.last_aggregation = django_timezone.now()
            except Exception as e:
                logger.error(f"Error aggregating statistics: {e}", exc_info=True)
    
    def _should_aggregate(self) -> bool:
        """Check if it's time to run statistics aggregation"""
        if self.last_aggregation is None:
            return True
        
        now = django_timezone.now()
        return (now - self.last_aggregation) >= self.aggregation_interval
    
    def force_aggregation(self):
        """Force an immediate statistics aggregation"""
        StatisticsAggregator.update_all_statistics()
        self.last_aggregation = django_timezone.now()


from django.db import models
from django.db.models import Count, Avg, Sum, Q
from django.utils import timezone
from datetime import timedelta


class BotStatus(models.Model):
    """Track bot status and metrics"""
    timestamp = models.DateTimeField(auto_now_add=True)
    total_servers = models.IntegerField(default=0)
    total_players = models.IntegerField(default=0)
    open_lobbies = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Bot statuses'
    
    def __str__(self):
        return f"Status at {self.timestamp}: {self.total_players} players, {self.open_lobbies} lobbies"


class NotificationLog(models.Model):
    """Log player threshold notifications"""
    timestamp = models.DateTimeField(auto_now_add=True)
    guild_id = models.BigIntegerField()
    player_count = models.IntegerField()
    threshold = models.IntegerField()
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"Notification at {self.timestamp}: {self.player_count} players (threshold: {self.threshold})"


class GameSession(models.Model):
    """
    Track individual game sessions.
    A game is defined as: lobby -> in_game (5+ mins) -> debrief
    """
    # Server information
    server_id = models.CharField(max_length=255, db_index=True)
    server_name = models.CharField(max_length=255)
    server_address = models.CharField(max_length=100)
    
    # Game details
    map_name = models.CharField(max_length=100, db_index=True)
    game_mode = models.CharField(max_length=100, default='Unknown')
    region = models.CharField(max_length=50, default='Unknown')
    
    # Game state tracking
    lobby_start = models.DateTimeField(null=True, blank=True)
    game_start = models.DateTimeField(db_index=True)  # When game transitioned to in_game
    game_end = models.DateTimeField(null=True, blank=True)  # When game transitioned to debrief
    
    # Player counts
    players_at_start = models.IntegerField(default=0)
    players_at_end = models.IntegerField(default=0)
    max_players_during_game = models.IntegerField(default=0)
    
    # Game attributes
    competitive = models.BooleanField(default=False)
    autobalance = models.BooleanField(default=False)
    rank_restricted = models.BooleanField(default=False)
    
    # Status tracking
    is_valid_game = models.BooleanField(default=False)  # True if game lasted 5+ minutes
    duration_seconds = models.IntegerField(null=True, blank=True)  # Calculated duration
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-game_start']
        indexes = [
            models.Index(fields=['-game_start']),
            models.Index(fields=['server_id', '-game_start']),
            models.Index(fields=['map_name', '-game_start']),
            models.Index(fields=['is_valid_game', '-game_start']),
        ]
    
    def __str__(self):
        return f"{self.server_name} - {self.map_name} at {self.game_start}"
    
    def calculate_duration(self):
        """Calculate and store game duration if game has ended"""
        if self.game_start and self.game_end:
            duration = (self.game_end - self.game_start).total_seconds()
            self.duration_seconds = int(duration)
            # A valid game is one that lasted at least 5 minutes
            self.is_valid_game = duration >= 300  # 5 minutes = 300 seconds
            return self.duration_seconds
        return None
    
    def save(self, *args, **kwargs):
        """Override save to automatically calculate duration"""
        if self.game_end:
            self.calculate_duration()
        super().save(*args, **kwargs)


class PlayerSnapshot(models.Model):
    """
    Track player count snapshots over time.
    Records total active players across all servers at regular intervals.
    """
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    total_players = models.IntegerField(default=0)
    total_servers = models.IntegerField(default=0)
    open_lobbies = models.IntegerField(default=0)
    games_in_progress = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.timestamp}: {self.total_players} players, {self.total_servers} servers"


class ServerStatistics(models.Model):
    """
    Aggregated statistics for servers.
    Periodically computed to avoid expensive queries.
    """
    server_id = models.CharField(max_length=255, unique=True, db_index=True)
    server_name = models.CharField(max_length=255)
    
    # Game count statistics
    total_games = models.IntegerField(default=0)
    total_valid_games = models.IntegerField(default=0)  # Games that lasted 5+ minutes
    
    # Time statistics
    last_game_date = models.DateTimeField(null=True, blank=True)
    first_game_date = models.DateTimeField(null=True, blank=True)
    
    # Player statistics
    avg_players_per_game = models.FloatField(default=0.0)
    total_player_minutes = models.IntegerField(default=0)  # Sum of all player*minutes
    
    # Last update
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-total_valid_games']
        verbose_name_plural = 'Server statistics'
    
    def __str__(self):
        return f"{self.server_name}: {self.total_valid_games} valid games"


class MapStatistics(models.Model):
    """
    Aggregated statistics for maps.
    Tracks which maps are played most frequently.
    """
    map_name = models.CharField(max_length=100, unique=True, db_index=True)
    
    # Game count statistics
    total_games = models.IntegerField(default=0)
    total_valid_games = models.IntegerField(default=0)
    
    # Time statistics
    last_played = models.DateTimeField(null=True, blank=True)
    avg_game_duration = models.FloatField(default=0.0)  # In seconds
    
    # Player statistics
    avg_players_per_game = models.FloatField(default=0.0)
    
    # Last update
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-total_valid_games']
        verbose_name_plural = 'Map statistics'
    
    def __str__(self):
        return f"{self.map_name}: {self.total_valid_games} valid games"


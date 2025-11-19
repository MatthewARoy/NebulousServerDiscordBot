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
    Track individual game sessions with unique IDs.
    Each game is saved immediately when it starts and updated when it ends.
    A valid game is defined as: in_game for 5+ minutes -> debrief
    """
    # Unique identifier (Django auto-generates this as primary key)
    # Access via game.id or game.pk
    
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
    has_password = models.BooleanField(default=False)  # Password protected server
    
    # Status tracking
    is_ongoing = models.BooleanField(default=True, db_index=True)  # False when game ends
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
            models.Index(fields=['is_ongoing', '-game_start']),  # For recovery queries
        ]
    
    def __str__(self):
        status = "ongoing" if self.is_ongoing else "completed"
        return f"Game #{self.id}: {self.server_name} - {self.map_name} ({status})"
    
    def calculate_duration(self):
        """Calculate and store game duration if game has ended"""
        if self.game_start and self.game_end:
            duration = (self.game_end - self.game_start).total_seconds()
            self.duration_seconds = int(duration)
            # A valid game is one that lasted at least 5 minutes
            self.is_valid_game = duration >= 300  # 5 minutes = 300 seconds
            return self.duration_seconds
        return None
    
    def end_game(self, end_time, players_at_end):
        """Mark game as ended and calculate final statistics"""
        self.game_end = end_time
        self.players_at_end = players_at_end
        self.is_ongoing = False
        self.calculate_duration()
        self.save()
    
    def save(self, *args, **kwargs):
        """Override save to automatically calculate duration"""
        if self.game_end and self.is_ongoing:
            self.calculate_duration()
            self.is_ongoing = False
        super().save(*args, **kwargs)


class PlayerSnapshot(models.Model):
    """
    Track player count snapshots over time.
    Records total active players across all servers at regular intervals.
    
    NOTE: This is different from game tracking - it captures overall community
    activity independent of individual games. Kept for historical player count data.
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


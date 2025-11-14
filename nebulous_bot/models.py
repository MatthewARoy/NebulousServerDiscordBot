from django.db import models


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


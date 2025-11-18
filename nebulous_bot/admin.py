from django.contrib import admin
from .models import (
    BotStatus, NotificationLog, GameSession, PlayerSnapshot, 
    ServerStatistics, MapStatistics
)


@admin.register(BotStatus)
class BotStatusAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'total_servers', 'total_players', 'open_lobbies')
    list_filter = ('timestamp',)
    readonly_fields = ('timestamp',)


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'guild_id', 'player_count', 'threshold')
    list_filter = ('timestamp', 'guild_id')
    readonly_fields = ('timestamp',)


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = (
        'game_start', 'server_name', 'map_name', 'players_at_start', 
        'duration_seconds', 'is_valid_game'
    )
    list_filter = ('is_valid_game', 'map_name', 'region', 'competitive', 'game_start')
    search_fields = ('server_name', 'map_name', 'server_id')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Server Information', {
            'fields': ('server_id', 'server_name', 'server_address', 'region')
        }),
        ('Game Details', {
            'fields': ('map_name', 'game_mode', 'competitive', 'autobalance', 'rank_restricted')
        }),
        ('Timing', {
            'fields': ('lobby_start', 'game_start', 'game_end', 'duration_seconds', 'is_valid_game')
        }),
        ('Player Counts', {
            'fields': ('players_at_start', 'players_at_end', 'max_players_during_game')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(PlayerSnapshot)
class PlayerSnapshotAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'total_players', 'total_servers', 'open_lobbies', 'games_in_progress')
    list_filter = ('timestamp',)
    readonly_fields = ('timestamp',)


@admin.register(ServerStatistics)
class ServerStatisticsAdmin(admin.ModelAdmin):
    list_display = (
        'server_name', 'total_valid_games', 'avg_players_per_game', 
        'total_player_minutes', 'last_game_date'
    )
    list_filter = ('last_updated',)
    search_fields = ('server_name', 'server_id')
    readonly_fields = ('last_updated',)


@admin.register(MapStatistics)
class MapStatisticsAdmin(admin.ModelAdmin):
    list_display = (
        'map_name', 'total_valid_games', 'avg_players_per_game', 
        'avg_game_duration', 'last_played'
    )
    list_filter = ('last_updated',)
    search_fields = ('map_name',)
    readonly_fields = ('last_updated',)


from django.contrib import admin
from .models import (
    BotStatus, GameSession, PlayerSnapshot
)


@admin.register(BotStatus)
class BotStatusAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'total_servers', 'total_players', 'open_lobbies')
    list_filter = ('timestamp',)
    readonly_fields = ('timestamp',)


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'game_start', 'server_name', 'map_name', 'players_at_start', 
        'duration_seconds', 'is_valid_game', 'is_ongoing'
    )
    list_filter = ('is_valid_game', 'is_ongoing', 'has_password', 'map_name', 'region', 'competitive', 'game_start')
    search_fields = ('server_name', 'map_name', 'server_id')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Server Information', {
            'fields': ('server_id', 'server_name', 'server_address', 'region', 'has_password')
        }),
        ('Game Details', {
            'fields': ('map_name', 'game_mode', 'competitive', 'autobalance', 'rank_restricted')
        }),
        ('Timing', {
            'fields': ('lobby_start', 'game_start', 'game_end', 'duration_seconds', 'is_valid_game', 'is_ongoing')
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


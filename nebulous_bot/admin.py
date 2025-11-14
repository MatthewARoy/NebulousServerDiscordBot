from django.contrib import admin
from .models import BotStatus, NotificationLog


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


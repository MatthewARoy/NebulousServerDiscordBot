import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Discord Configuration
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    APPLICATION_ID = os.getenv('APPLICATION_ID')
    
    # Multi-server configuration
    # Format: [{"guild_id": 123, "status_channel_id": 456, "notification_channel_id": 789, "notification_role_id": 101112}, ...]
    SERVER_CONFIGS = []
    
    # Notification Configuration
    PLAYER_THRESHOLD = int(os.getenv('PLAYER_THRESHOLD', 40))  # Minimum players to trigger notification
    NOTIFICATION_INTERVAL = int(os.getenv('NOTIFICATION_INTERVAL', 3600))  # seconds - minimum time between notifications (default 1 hour)
    
    @classmethod
    def _load_server_configs(cls):
        """Load bootstrap server configurations from environment variables.

        Empty / unset is now allowed: guilds added via Discord's Add-to-Server
        flow can self-configure with !setstatuschannel and friends, which write
        to the GuildConfig table. The env-var SERVER_CONFIGS is just the
        original way and stays supported as a "factory default" set of guilds.
        """
        server_configs_json = os.getenv('SERVER_CONFIGS', '').strip()
        if not server_configs_json:
            cls.SERVER_CONFIGS = []
            return

        try:
            configs = json.loads(server_configs_json)
            if not isinstance(configs, list):
                raise ValueError("SERVER_CONFIGS must be a JSON array")

            cls.SERVER_CONFIGS = [
                {
                    'guild_id': int(config['guild_id']),
                    'status_channel_id': int(config['status_channel_id']),
                    'notification_channel_id': int(config.get('notification_channel_id', 0)) if config.get('notification_channel_id') else None,
                    'notification_role_id': int(config.get('notification_role_id', 0)) if config.get('notification_role_id') else None
                }
                for config in configs
            ]
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid SERVER_CONFIGS format: {e}. Expected format: [{{'guild_id': 123, 'status_channel_id': 456, 'notification_channel_id': 789, 'notification_role_id': 101112}}]") from e

    @classmethod
    def get_server_configs(cls):
        """Return the merged list of guild configs (env bootstrap + DB rows).

        Env entries supply factory-default channels for guilds the maintainer
        deploys with. DB rows (written by admin commands) override on
        guild_id collision and add new guilds. A guild whose DB row has a
        null status_channel_id is omitted: the admin hasn't picked a
        channel yet, so there's nowhere to post.

        Always call this (never the bare cls.SERVER_CONFIGS attribute) when
        you need the live, current set of guilds the bot should act on.
        """
        # Lazy import to avoid Django app-loading at module import time.
        from nebulous_bot.models import GuildConfig

        merged = {entry['guild_id']: dict(entry) for entry in cls.SERVER_CONFIGS}

        for row in GuildConfig.objects.all():
            if row.status_channel_id is None:
                merged.pop(row.guild_id, None)
                continue
            merged[row.guild_id] = {
                'guild_id': row.guild_id,
                'status_channel_id': row.status_channel_id,
                'notification_channel_id': row.notification_channel_id,
                'notification_role_id': row.notification_role_id,
            }

        return list(merged.values())
    
    # Steam Configuration
    STEAM_API_KEY = os.getenv('STEAM_API_KEY')
    GAME_NAME = "Nebulous: Fleet Command"
    NEBULOUS_APP_ID = 887570  # Steam App ID for Nebulous: Fleet Command
    
    # Bot Configuration
    COMMAND_PREFIX = "!"
    UPDATE_INTERVAL = 30  # seconds - update every 30 seconds
    STATUS_MESSAGE_REFRESH_INTERVAL = int(os.getenv('STATUS_MESSAGE_REFRESH_INTERVAL', 86400))  # seconds - create new message daily (86400 = 24 hours)
    MAX_SERVERS_DISPLAY = 20
    
    # Embed Configuration
    EMBED_COLOR = 0x00ff00  # Green
    EMBED_COLOR_NO_SERVERS = 0xff0000  # Red
    
    # Version Information
    VERSION = "2.4.1"
    CHANGELOG = [
        {
            "version": "2.4.1",
            "date": "2026-07-06",
            "changes": [
                "Games in progress now survive bot restarts and are tracked to completion (statistics accuracy fix)"
            ]
        },
        {
            "version": "2.4.0",
            "date": "2026-07-06",
            "changes": [
                "Added !nextgame newplayer — get pinged only for new-player servers (stacks with ptb, modded, lobby, --skip)",
                "-skip now works as an alias of --skip"
            ]
        },
        {
            "version": "2.3.5",
            "date": "2026-07-06",
            "changes": [
                "Fixed the first !graph or !formation after a restart hanging the bot for minutes"
            ]
        },
        {
            "version": "2.3.4",
            "date": "2026-07-06",
            "changes": [
                "Faster and lighter: the bot now polls Steam once per update cycle and uses less memory at startup",
                "The daily 6pm Pacific !nextgame queue alert now respects daylight saving time",
                "Busy commands have short cooldowns and clearer error messages"
            ]
        },
        {
            "version": "2.3.3",
            "date": "2026-05-04",
            "changes": [
                "Added !nextgame lobby option to only ping when a lobby is ready (suppresses debrief alerts); stacks with ptb and --skip"
            ]
        },
        {
            "version": "2.3.2",
            "date": "2026-05-01",
            "changes": [
                "Fixed a rare error that could affect the live server status message right after the bot started up",
                "Stability improvements"
            ]
        },
        {
            "version": "2.3.1",
            "date": "2026-03-03",
            "changes": [
                "Improved !nextgame queue handling for standard and PTB modes",
                "Added a daily 6pm PST queue-interest alert",
                "Sanitized URL-like text in server names for safer alerts"
            ]
        },
        {
            "version": "2.3.0",
            "date": "2026-01-01",
            "changes": [
                "Default `!listservers` now includes PTB/test-branch servers without needing a flag",
                "`!listservers` updates now respect PTB/all filters when the bot refreshes tracked messages",
                "Added fallback logic so the `!listservers all` cache is still populated even if Steam's all-server fetch fails"
            ]
        },
        {
            "version": "2.2.0",
            "date": "2025-12-26",
            "changes": [
                "Added dynamic stable version detection from majority of servers",
                "Added PTB (test branch) server identification with 🧪 indicator",
                "Added !nextgame ptb command for PTB-only notifications",
                "Added !listservers all command to show all servers (empty/private/bots)",
                "PTB servers now display version info and test branch status"
            ]
        },
        {
            "version": "2.1.0",
            "date": "2025-11-29",
            "changes": [
                "Added !graph command to visualize player/server data over time",
                "Improved !nextgame to immediately notify if games are available",
                "Grouped notifications by channel to reduce spam",
                "Updated !nextgame triggers: lobby with 3+ players (joinable) or games entering debrief"
            ]
        },
        {
            "version": "2.0.0",
            "date": "2025-11-27",
            "changes": [
                "Added !nextgame notification system",
                "Added game statistics tracking (!stats, !mapstats, !serverstats)",
                "Added live message updates for server lists",
                "Improved multi-server support"
            ]
        },
        {
            "version": "1.0.0",
            "date": "2025-11-18",
            "changes": [
                "Initial release with server monitoring",
                "Basic commands: !listservers, !openlobbies, !status",
                "Real-time server status updates"
            ]
        }
    ]
    
    @classmethod
    def validate(cls):
        """Validate that all required configuration is present"""
        # Load env-var bootstrap server configurations (may be empty)
        cls._load_server_configs()

        # Validate required variables
        required_vars = [
            ('DISCORD_TOKEN', cls.DISCORD_TOKEN),
            ('STEAM_API_KEY', cls.STEAM_API_KEY),
            ('APPLICATION_ID', cls.APPLICATION_ID)
        ]

        missing = [name for name, value in required_vars if not value]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        # Validate the shape of each env-var bootstrap entry. Per-guild DB
        # rows are validated when written by the admin commands, not here.
        for i, config in enumerate(cls.SERVER_CONFIGS):
            if not config.get('guild_id'):
                raise ValueError(f"Server config {i}: missing guild_id")
            if not config.get('status_channel_id'):
                raise ValueError(f"Server config {i}: missing status_channel_id")

        return True

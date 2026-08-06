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

    # How old the server cache may be before a command will pay for its own
    # Steam+A2S sweep. The monitoring loop refreshes every UPDATE_INTERVAL, so
    # anything under this bound means the loop is keeping up and commands can
    # answer straight from cache. Exceeding it means the loop is stalled or
    # dead, and the command sweeps rather than showing stale data.
    SERVER_CACHE_MAX_AGE = 45  # seconds (UPDATE_INTERVAL + margin for one sweep)

    # A2S queries run on SteamAPI's OWN thread pool, never the asyncio default
    # executor. The default pool is min(32, cpu_count + 4) — six workers on the
    # production VM (cpu_count 2) — and is shared with the statistics writer
    # and, since aiodns isn't installed, aiohttp's DNS resolution. A sweep
    # sized to that pool would own all of it for most of a cycle.
    A2S_MAX_CONCURRENCY = 6

    # Per-UDP-exchange timeout handed to python-valve. A full query is two
    # exchanges (challenge + reply) and each server gets two queries, so the
    # in-thread worst case is 4x this. Keep 4x below A2S_QUERY_TIMEOUT:
    # asyncio.wait_for abandons the future but CANNOT cancel a running thread,
    # so a longer socket timeout would leave orphans holding pool workers
    # after their semaphore slot was already handed to the next server.
    A2S_SOCKET_TIMEOUT = 1.5
    A2S_QUERY_TIMEOUT = 7.0  # > 4 * A2S_SOCKET_TIMEOUT

    # Whole-sweep backstop. Per-server results are kept individually, so
    # exceeding this only costs Steam-fallback data for the stragglers.
    # A measured 24-server sweep runs in ~5s.
    A2S_SWEEP_TIMEOUT = 20.0

    # Consecutive failed A2S sweeps before a server is treated as unreachable
    # and hidden from the default view. Steam's master list keeps advertising
    # servers that have died or moved, and those entries never answer A2S, so
    # they would otherwise keep their last-known Steam player count forever —
    # rendering as a green, joinable lobby and triggering !nextgame pings for
    # a server nobody can join. One or two misses stay tolerated so ordinary
    # packet loss changes nothing.
    A2S_UNREACHABLE_THRESHOLD = 3  # x UPDATE_INTERVAL = 90s of total silence
    STATUS_MESSAGE_REFRESH_INTERVAL = int(os.getenv('STATUS_MESSAGE_REFRESH_INTERVAL', 86400))  # seconds - create new message daily (86400 = 24 hours)
    MAX_SERVERS_DISPLAY = 20
    
    # Embed Configuration
    EMBED_COLOR = 0x00ff00  # Green
    EMBED_COLOR_NO_SERVERS = 0xff0000  # Red

    # Community advice voting (!advice add / !advice remove): votes needed
    # to decide a ballot (env-overridable so a small test server can use 1).
    ADVICE_VOTE_THRESHOLD = int(os.getenv('ADVICE_VOTE_THRESHOLD', 5))

    # Version Information
    VERSION = "2.7.0"
    CHANGELOG = [
        {
            "version": "2.7.0",
            "date": "2026-07-30",
            "changes": [
                "!advice add <tip> — propose new advice; 5+ 👍 from the community adds it to the knowledge pool, 5+ 👎 marks it incorrect",
                "!advice remove <id> — vote out advice that turns out to be wrong (5+ 👍 removes it)",
                "!advice list — audit the whole knowledge pool by category, including the incorrect pool; !advice pending shows open votes"
            ]
        },
        {
            "version": "2.6.1",
            "date": "2026-07-28",
            "changes": [
                "Fixed !serverstats showing wrong per-server numbers — game counts, player-hours, and last-game times now cover each server's full history",
                "Servers no longer appear more than once in the !serverstats list"
            ]
        },
        {
            "version": "2.6.0",
            "date": "2026-07-13",
            "changes": [
                "New !advice command — search curated fleet-building tips from the community (try !advice point defense)",
                "!advice tags lists the searchable topics; every tip credits its author with a link to the original message"
            ]
        },
        {
            "version": "2.5.0",
            "date": "2026-07-07",
            "changes": [
                "Internal restructuring for reliability — no visible changes; all commands work exactly as before",
                "!help now groups commands by category"
            ]
        },
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

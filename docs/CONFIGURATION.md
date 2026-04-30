# Configuration reference

All configuration is read from environment variables, typically via a `.env`
file in the project root. `nebulous_bot/config.py` is the source of truth — if
this document drifts, that file wins.

## Required

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token from the Discord Developer Portal. |
| `APPLICATION_ID` | Application ID from the Developer Portal (General Information). |
| `STEAM_API_KEY` | Steam Web API key. |
| `SERVER_CONFIGS` | JSON array of `{guild_id, status_channel_id, …}` entries — see below. |

### `SERVER_CONFIGS`

A JSON array on a single line. Each entry maps one Discord server to:

- `guild_id` *(required)* — the Discord server ID.
- `status_channel_id` *(required)* — channel for the live-updating status embed.
- `notification_channel_id` *(optional)* — channel for player-threshold pings.
- `notification_role_id` *(optional)* — role to mention on threshold pings.

Single-server example:

```env
SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 9876543210}]
```

With threshold notifications:

```env
SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 9876543210, "notification_channel_id": 9876543210, "notification_role_id": 1122334455}]
```

Multiple guilds:

```env
SERVER_CONFIGS=[{"guild_id": 111, "status_channel_id": 222}, {"guild_id": 333, "status_channel_id": 444}]
```

## Optional

| Variable | Default | Description |
|---|---|---|
| `UPDATE_INTERVAL` | `30` | Seconds between Steam server polls. |
| `STATUS_MESSAGE_REFRESH_INTERVAL` | `86400` | Seconds before posting a fresh status message (defaults to once per day). |
| `MAX_SERVERS_DISPLAY` | `20` | Maximum servers shown in the status embed. |
| `PLAYER_THRESHOLD` | `40` | Player count required to trigger a threshold notification. |
| `NOTIFICATION_INTERVAL` | `3600` | Minimum seconds between threshold notifications. |
| `DB_PATH` | unset | Override the SQLite path. Useful when mounting persistent storage (e.g. `/mnt/data/db.sqlite3` in production). |
| `DEPLOYMENT_TIME` | unset | ISO-8601 or Unix timestamp recorded as the deployment time, displayed by `!status`. Set this in the deploy script. |

## Threshold notifications

To opt in to player-count pings:

1. Create a role in your Discord server (e.g. *Nebulous Notifications*).
2. Add `notification_channel_id` and `notification_role_id` to the matching
   `SERVER_CONFIGS` entry.
3. Members self-assign the role.

The bot pings the role at most once per `NOTIFICATION_INTERVAL`, even if
player count crosses the threshold multiple times.

# Architecture

A short tour of how the project fits together.

## Stack

- **Python 3.11**, **Django 4.2 LTS** (used for ORM, migrations, admin, and a
  tiny HTTP healthcheck — there's no user-facing web UI). Pinned `<5.0`
  deliberately: LTS support and a smaller footprint on the RAM-constrained VM.
- **discord.py** for the bot.
- **SQLite** for persistence. The DB lives at `db.sqlite3` in development and
  on a mounted block-storage volume in production.
- **Docker** + **Docker Compose** for deployment.
- **Oracle Cloud Infrastructure** Always Free tier for the production VM
  (E2.1.Micro; the accepted 2.10.0 image is Linux/amd64).

## Layout

```
nebulous_project/        Django project (settings, urls, wsgi/asgi)
nebulous_bot/            The bot itself (Django app)
  ├── management/commands/runbot.py   ← entry point: `python manage.py runbot`
  ├── server_monitor.py               background polling + state machine
  ├── server_formatter.py             Discord embed rendering
  ├── steam_api.py                    Steam Web API client
  ├── statistics_tracker.py           game-session and snapshot bookkeeping
  ├── command_logging.py              `/command` usage instrumentation
  ├── graph_generator.py              matplotlib renderer for `/graph`
  ├── models.py                       Django ORM models
  └── migrations/                     schema history
formation_optimizer/     Standalone library used by `/formation`
deployment/              Docker, Oracle scripts, and helpers
docs/                    Documentation (this directory)
```

## Runtime shape

`python manage.py runbot` is the only entry point in production. It:

1. Builds a `discord.ext.commands.Bot` with mention/DM fallback and registers
   seven cogs. Public commands use hybrid slash/prefix decorators; owner
   maintenance commands remain prefix-only. Production explicitly disables all
   privileged intents. Application-command sync is a deliberate owner action,
   never a startup or reconnect side effect.
2. On `on_ready`, validates `Config`, constructs a `ServerMonitor`, attaches a
   `ServerFormatter`, and kicks off the monitoring loop.
3. The monitoring loop polls Steam every `UPDATE_INTERVAL` seconds, updates
   the cached server list, refreshes tracked messages, fires `/nextgame`
   notifications, and writes `PlayerSnapshot` records.

The container also runs a small Gunicorn WSGI server on port 8000 (started by
`start-server.sh`) purely so the orchestrator can hit `/health/` for liveness.

## Data model (high level)

- `GameSession` — one row per detected game (lobby → in-game ≥5 min →
  debrief). Stores duration, map, players-at-start, server, validity.
- `PlayerSnapshot` — periodic (5-minute) sample of total players, servers,
  lobbies, and games-in-progress. Drives `/graph` and `/stats`.
- `BotStatus` — recorded on `/refresh`; quick health log.
- `CommandLog` — every command invocation: success/error, latency, context
  (guild / DM / thread), guild + user identifiers.

`/stats`, `/mapstats`, `/serverstats` all aggregate from `GameSession` in
real time — there are no precomputed rollup tables.

## State that lives in memory only

`ServerMonitor` keeps caches that are rebuilt on each restart:

- `cached_servers`, `cached_all_servers` — the latest Steam snapshots.
- `game_start_times` — per-server state-transition timestamps used to detect
  lobby→game and game→debrief transitions.
- `next_game_waiters` — pending `/nextgame` opt-ins; users must subscribe again
  after a restart. Keys include user, PTB, modded and new-player modes.
- `tracked_messages` — recent command-response messages that should keep
  refreshing (capped at 3 per channel). Interaction-created messages are edited using
  bot authentication so refreshes survive interaction-token expiry.

Long-running data (game history, snapshots, command logs) goes through the
ORM into SQLite.

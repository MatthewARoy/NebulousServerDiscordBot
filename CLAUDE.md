# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Discord bot that polls the Steam Web API for **Nebulous: Fleet Command**
servers, maintains live-updating status embeds, and tracks game statistics.
Python 3.11 + Django (ORM/migrations/admin only — no web UI) + discord.py +
SQLite. Production is a single Docker container on an Oracle Cloud
**Always Free VM with ~503 MiB usable RAM** — memory is the binding
constraint on every decision (see docs/OPS.md for the OOM postmortem).

The bot is **stable in production**. Prefer small, independently verifiable
changes; a ranked improvement backlog from the July 2026 review lives in
`docs/CODE_REVIEW_2026-07.md`.

## Commands

Local dev uses `.venv` (Windows: `.venv/Scripts/python`, POSIX: `.venv/bin/python`).
Create if missing: `py -3.11 -m venv .venv` then
`.venv/Scripts/python -m pip install -r requirements.txt pytest ruff`.

```bash
.venv/Scripts/python -m ruff check .        # lint (F + B rules only, bug-focused)
.venv/Scripts/python -m pytest -q           # all tests (fast, no network/DB)
.venv/Scripts/python -m pytest nebulous_bot/tests/test_waiter_modes.py -q   # one file
.venv/Scripts/python -m pytest -k modded -q                                 # by keyword
```

Django commands need env vars that tests stub automatically but `manage.py`
does not: `DISCORD_TOKEN=x APPLICATION_ID=0 STEAM_API_KEY=x` (any values).

```bash
DISCORD_TOKEN=x APPLICATION_ID=0 STEAM_API_KEY=x .venv/Scripts/python manage.py check
DISCORD_TOKEN=... .venv/Scripts/python manage.py migrate    # local sqlite
DISCORD_TOKEN=... .venv/Scripts/python manage.py runbot     # run the bot (needs real tokens + .env)
```

Full verification checklist (run before committing): `.claude/skills/verify/SKILL.md`.
Release/version-bump procedure: `.claude/skills/release/SKILL.md`.
Deploy is `deployment/oracle/deploy-to-oracle.sh` — user-run, needs local
SSH config not in the repo.

## Architecture

`python manage.py runbot` is the only production entry point
(`nebulous_bot/management/commands/runbot.py`, ~1,900 lines). It defines
**every Discord command inline inside `Command.handle()`** as closures over
`server_monitor` / `formatter` nonlocals — there are no cogs. To find a
command, grep runbot.py for `@bot.command(name='...')`.

The runtime core is `ServerMonitor` (`server_monitor.py`), an asyncio loop
that every 30 s (`Config.UPDATE_INTERVAL`):

1. Fetches servers via `SteamAPI` (`steam_api.py`) — Steam `GetServerList`
   HTTP call, then per-server A2S rules queries (python-valve, run in
   threads, semaphore-limited) that yield the real game state
   (`inprogress` rule → `lobby` / `in_game` / `debrief`), map, version, and
   mod list.
2. Tracks state transitions (`game_start_times`, `recent_debrief_transitions`).
3. Edits the per-guild pinned status embed and the last 3 tracked command
   responses per channel (self-refreshing messages; retired ones get 💀 in
   the title).
4. Fires `!nextgame` waitlist notifications. Waiter keys are
   `(user_id, ptb_only, modded_only)` tuples — one user can wait in several
   queue modes at once.
5. Persists statistics via `StatisticsService` (`statistics_tracker.py`):
   `GameSession` rows (a "valid game" = in_game ≥5 min → debrief) and
   5-minute `PlayerSnapshot` rows. Ongoing games are recovered from the DB
   on restart.

A separate 60 s watchdog task restarts the monitoring loop if it dies.

Cross-cutting details that take multi-file reading to discover:

- **Guild config is merged from two sources** (`Config.get_server_configs`):
  the env-var `SERVER_CONFIGS` bootstrap list, overridden per-guild by
  `GuildConfig` DB rows written by the `!setstatuschannel` family of admin
  commands. Always call `get_server_configs()`, never read
  `Config.SERVER_CONFIGS` directly.
- **PTB (test-branch) detection is relative, not configured**: the "stable
  version" is the majority version across all servers
  (`ServerMonitor._determine_stable_version`), pushed into `SteamAPI`; any
  server with a higher version is flagged `is_test_branch`.
- **Two server caches**: `cached_servers` (filtered: no empty/bot/private
  servers) and `cached_all_servers` (everything, for `!listservers all` and
  PTB detection).
- **Django ORM is sync; the bot is async.** Every DB touch from async code
  goes through `sync_to_async` (see any command in runbot.py) or
  `run_in_executor`. Never call the ORM directly from the event loop.
- `formation_optimizer/` is a standalone, Django-free library used by
  `!formation` (fleet XML in → compacted fleet + optional GIF out).
  Fleet-file units are 10 m per unit (`FLEET_UNIT_TO_METERS`).

## Hard constraints and conventions

- **Memory budget**: matplotlib + numpy add ~80–120 MiB RSS and are lazily
  imported inside `graph_generator.py` for exactly this reason. Never add
  heavy imports at module scope on the runbot import path; follow the lazy
  pattern. (Known violation: runbot's top-level `formation_optimizer`
  import — see review item #12.)
- **Version bumps are user-facing**: `Config.VERSION` + `Config.CHANGELOG`
  (in `nebulous_bot/config.py`) power the `!version` command and are the
  source of truth; root `CHANGELOG.md` intentionally mirrors them for
  GitHub. Update both or neither.
- **Tests are pure-logic and DB-free** — CI runs pytest with no migrations,
  so tests construct `ServerMonitor` via `__new__` and set just the needed
  attributes (see `nebulous_bot/tests/test_waiter_modes.py`). Don't write
  tests that hit the ORM.
- **Migrations**: never edit an applied one; `0005` removed the aggregated
  statistics tables — stats are computed live from `GameSession` at query
  time.
- Timezone displays are PST-based (community convention); note there are
  currently two inconsistent PST definitions (review item #15).
- `docs/archive/` is historical only. Agent-authored plans/specs go in
  `docs/superpowers/plans/` and `docs/superpowers/specs/` (dated, kebab-case).
- Ops runbook (OOM triage, why `dnf-makecache` is masked on the VM):
  `docs/OPS.md`. Never commit VM IPs/SSH details (gitignored
  `ORACLE_CONNECT.md` convention).

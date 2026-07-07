# Code review — July 2026

Full-repo review performed 2026-07-06 (bot v2.3.3, `main` @ 5e2f6bf).
Baseline at review time: `ruff check .` clean, 26/26 tests passing.

Ranked backlog. Each item is small and independently shippable; the bot is
stable in production, so prefer one-item-at-a-time changes verified with the
loop in `.claude/skills/verify/SKILL.md`.

## P0 — Broken code

1. **`nebulous_bot/management/commands/test_statistics.py` crashes on any
   invocation.** It imports `ServerStatistics`, `MapStatistics` (removed from
   `models.py` by migration 0005) and `StatisticsAggregator` (never existed in
   the rewritten `statistics_tracker.py`). Verified:
   `manage.py test_statistics --verify` → `ImportError`. CI doesn't catch it
   because `manage.py check` doesn't import management commands and ruff can't
   see cross-module attribute existence.
   **Fix:** delete the file, or strip it down to the still-useful
   `--create-sample` path (sample `GameSession`/`PlayerSnapshot` rows are handy
   for exercising `!stats`/`!graph` locally) and drop `--aggregate`/the
   aggregate checks in `--verify`.

## P1 — Dead code (delete; no behavior change)

2. **`MockSteamAPI`** — `steam_api.py:580-616`. Unused everywhere; its
   `get_game_servers` signature has also drifted from the real one
   (no `include_all`), so it would break if someone did use it.
3. **`SteamAPI.get_server_info`** — `steam_api.py:64-88`. Never called.
4. **`ServerMonitor.get_servers_by_criteria`** — `server_monitor.py:844-868`.
   Never called; duplicates `filter_servers` and reads the wrong key
   (`server['map']` vs the `map` set by rules — another sign it rotted).
5. **`ServerFormatter.get_enhanced_status_icons`** — `server_formatter.py:190-198`.
   Never called, which also means `COMPETITIVE_EMOJI`, `AUTOBALANCE_EMOJI`,
   `RANK_RESTRICTED_EMOJI` never render anywhere. Delete all four, or wire the
   icons into `create_server_field_value` if the display is wanted.
6. **`ServerFormatter.__init__(server_monitor=None)`** — the attribute is
   stored and never read; `runbot.py` constructs `ServerFormatter()` bare.
   Remove the parameter.
7. **Unreachable loop-exit log** — `server_monitor.py:216`
   (`logger.error("Monitoring loop exited unexpectedly!")` after
   `while True` that only exits by `raise`).
8. **`blacklisted_servers = {}`** — `steam_api.py:212-214`. Empty placeholder
   checked on every server every cycle. Delete (trivial to re-add if ever
   needed).
9. **`limit` parameter of `SteamAPI.get_game_servers`** — accepted, never used.
10. **`NotificationLog` model + admin** — registered in `admin.py` but no code
    ever creates a row (threshold notifications in
    `_check_and_send_notification_for_server` don't log). Either start writing
    rows there, or drop model + admin + migration. `BotStatus` is near-dead
    too: rows are only written by the `!refresh` command and nothing reads
    them; `PlayerSnapshot` already covers the same data on a 5-min cadence.
11. **Unused dependencies** — `requirements.txt` lists `asyncio-throttle` and
    `requests`; neither is imported anywhere. Removing them shrinks the Docker
    image and the pip surface.

## P2 — Bugs / operational risks

12. ~~**`runbot.py:24` defeats the lazy-matplotlib memory win.**~~
    **REVERTED in 2.3.5 — the eager import was load-bearing.** The lazy
    import shipped in 2.3.4 and moved the numpy+matplotlib import (plus
    first-run font-cache build) from boot time into the first
    `!graph`/`!formation` call. On the 1/8-OCPU VM that import runs for
    minutes holding the GIL: blocked heartbeats, gateway resets, every
    command hung (observed in prod 2026-07-06 17:30–17:36). The import is
    now deliberately eager again — paid at boot before the event loop
    exists — and the Dockerfile pre-builds the matplotlib font cache into
    the image. Idle RSS returns to the pre-2.3.4 level the bot ran at
    stably for 8 weeks under the 350m container limit. Do not re-apply the
    lazy import; `graph_generator.py`'s internal lazy load stays (harmless).
13. **`!commandlogs` has no permission gate** — `runbot.py:1151`. Docstring
    says "admin/debugging only", it's `hidden=True`, but any user in any guild
    can run it and see usernames, guild names, and usage stats across all
    guilds. **Fix:** add `@commands.is_owner()`.
14. **Every cycle sweeps Steam twice** — `_update_server_list`
    (`server_monitor.py:262-265`) calls `get_game_servers()` and
    `get_game_servers(include_all=True)`: two `GetServerList` HTTP calls plus
    two full A2S rules sweeps every 30 s. **Fix:** fetch once with
    `include_all=True`, derive the filtered list in Python (the filter is
    name/players/bots-based and needs no extra data). Halves poll traffic,
    A2S queries, and cycle latency.
15. **Two conflicting definitions of "PST".** `server_monitor.py:13` uses a
    fixed UTC-8 (`PST`), `runbot.py` uses `pytz America/Los_Angeles`, Django
    uses `America/Los_Angeles`. Consequence: the "6pm PST" daily queue alert
    (`_check_daily_next_game_queue_alert`) fires at 5pm local during daylight
    time, and `game_start_times` transition timestamps are DST-naive.
    **Fix:** standardize on `zoneinfo.ZoneInfo("America/Los_Angeles")`
    (stdlib; also lets you drop the `pytz` dependency).
16. **`on_command_error` echoes raw exception text into the channel** —
    `runbot.py:1815-1828`. Internals leak to users and permission errors read
    badly. **Fix:** map common cases (`MissingPermissions`, `MissingRole`,
    `BadArgument`, cooldowns) to friendly messages; log the rest and reply
    generically.
17. **Latent waiter-removal trap** — `remove_next_game_waiter(user_id,
    ptb_only=True/False)` (`server_monitor.py:1172-1186`) builds the key with
    `modded_only` defaulted to `False`, so it can never remove a
    PTB+modded queue entry. All current callers pass `ptb_only=None` (remove
    all), so it's latent — but tighten the signature (accept `modded_only`, or
    drop the per-mode branch entirely since nothing uses it).
18. **No command cooldowns.** `!listservers`, `!openlobbies`, `!refresh`, and
    `!nextgame` each trigger a full `force_update()` (Steam + A2S sweep).
    A user can spam them. **Fix:** `@commands.cooldown(1, 15, BucketType.channel)`
    on the fetch-triggering commands, plus a friendly cooldown message in the
    error handler (pairs with #16).
19. **Unbounded log file on the tiny VM.** `settings.py` uses a plain
    `FileHandler` for `nebulous_bot.log` with INFO-level logging *per cycle*
    (several lines every 30 s ≈ tens of MB/month). **Fix:**
    `RotatingFileHandler` (e.g. 5 MB × 3), and consider demoting the
    per-iteration "iteration N starting / complete" logs to DEBUG.
20. **Fragile quote-swap JSON parse** — `_parse_nebulous_rules_json`
    (`steam_api.py:180`) does `json.loads(rules_data.replace("'", '"'))`,
    which corrupts any payload containing an apostrophe (server names, map
    names). **Fix:** try `json.loads` as-is, then `ast.literal_eval`, and only
    then the quote-swap fallback.
21. **`STATUS_PRIORITY` has no `debrief` entry** — `server_formatter.py:16-20`.
    Debrief servers sort in the "unknown" tier (above in-game). Probably
    unintended; add an explicit `'debrief'` priority (and a comment either way).
22. **New TCP connector + session every 30 s.** `_update_server_list` enters
    `async with self.steam_api`, creating and tearing down an aiohttp session
    each cycle. Keep one persistent session (create in `start_monitoring`,
    close in `stop_monitoring`).

## P3 — Structure / hygiene

23. **`runbot.py` (1,862 lines) defines every command inline inside
    `Command.handle()`.** Nothing is unit-testable and the closure state
    (`server_monitor`, `formatter` nonlocals) is invisible to tools. The
    standard discord.py shape is Cogs: `nebulous_bot/cogs/{servers,stats,
    nextgame,formation,setup,admin}.py`, with `runbot.py` reduced to bot
    setup + cog loading. Do this incrementally — one cog per PR, verify
    each with a live smoke test.
24. **Docs drift:** README and `docs/ARCHITECTURE.md` say "Django 5" but
    `requirements.txt` pins `Django>=4.2,<5.0` (and the deployed venv has
    4.2.x). Pick one; if staying on 4.2 LTS say so, it's a reasonable choice
    for the RAM budget.
25. **`has_password` is always `False`.** Steam's `GetServerList` doesn't
    return it and nothing sets it, so the `GameSession.has_password` column,
    the 🔒 icon logic, and the `no_password` filter never fire. Either derive
    it (the name heuristic in `_is_private_server` is the only signal) or
    note it as reserved.
26. **Test coverage is thin on the money paths.** The three bot test files
    cover region parsing, modded filtering, and waiter modes — good pure-logic
    picks. Highest-value additions, in order: rules→status parsing
    (`_create_enhanced_server_data`), `_filter_servers_for_waiter` skip/lobby
    semantics, `filter_servers`, `sanitize_server_name_for_display`, and
    `GraphGenerator.parse_graph_type`. All are pure and DB-free like the
    existing tests.
27. **Duplicated inline imports.** `runbot.py` re-imports `sync_to_async`,
    models, `pytz` etc. inside a dozen command bodies (`!stats` imports pytz
    twice at different scopes). Falls out naturally during the cog split (#23).

## Found post-review (observed in production logs, 2026-07-06 deploy)

28. **Ongoing-game recovery never runs.** On every bot startup:
    `ERROR ... statistics_tracker Error recovering ongoing games: You cannot
    call this from an async context - use a thread or sync_to_async.`
    `GameSessionTracker.__init__` runs inside async `on_ready` (via
    `ServerMonitor.__init__` → `StatisticsService()`), so the
    `GameSession.objects.filter(is_ongoing=True)` query trips Django's
    async-context guard; the `list()` workaround in the comment predates that
    guard. Consequence: games in progress across a restart are never
    reattached — their rows stay `is_ongoing=True` forever and the game is
    double-counted when re-detected. Pre-existing (file unchanged since
    2026-04-29); observed on the 2.3.4 deploy. **Fix:** defer
    `_recover_ongoing_games()` to the first `StatisticsService.update()`
    call, which already runs in an executor thread.

## Non-issues (checked, fine as-is)

- `Config.CHANGELOG` vs root `CHANGELOG.md` duplication is documented as
  intentional (bot reads its own changelog for `!version`).
- Lazy matplotlib in `graph_generator.py` is correct — the leak is only via
  `formation_optimizer` (#12).
- The health-check / self-healing monitor loop pattern (task + 60 s watchdog)
  is redundant-but-harmless belt-and-suspenders.
- `docs/archive/` is clearly labeled as historical; not counted as dead code.
- Env+DB guild-config merge (`Config.get_server_configs`) is clean and
  well-commented.

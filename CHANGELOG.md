# Changelog

The bot reads its own changelog from `nebulous_bot/config.py` (`Config.CHANGELOG`)
to power the in-Discord `!version` command, so that file is the source of truth
for current and recent releases. This document mirrors it for readers on GitHub.

## 2.4.1 — 2026-07-06

- Games in progress now survive bot restarts and are tracked to completion
  (statistics accuracy fix).

(Maintainer notes: review item #28 — recovery ran in async `on_ready` where
the ORM raises `SynchronousOnlyOperation`, so it silently failed since ~Dec.
Now deferred to the first executor-thread `update()`. Recovery also closes
stale `is_ongoing` rows older than 6h as invalid — prod had 595 of them,
which fixed recovery would otherwise have "finalized" with months-long
durations, poisoning `!stats`.)

## 2.4.0 — 2026-07-06

- Added `!nextgame newplayer` (aliases `np`, `beginner`) — get pinged only for
  new-player servers, detected from the server name. Stacks with `ptb`,
  `modded`, `lobby`, and `--skip`; each combination is its own queue.
- `-skip` now works as an alias of `--skip`.

## 2.3.5 — 2026-07-06

- Fixed the first `!graph` or `!formation` after a restart hanging the bot
  for minutes.

(Maintainer notes: reverts the 2.3.4 lazy `formation_optimizer` import — it
moved the multi-minute numpy/matplotlib import + font-cache build into
serving time on the fractional-CPU VM, starving the event loop. The import
is eager again, with a code comment explaining why, and the Dockerfile now
bakes the matplotlib font cache into the image. Review item #12 updated.)

## 2.3.4 — 2026-07-06

- Faster and lighter: the bot now polls Steam once per update cycle and uses
  less memory at startup.
- The daily 6pm Pacific `!nextgame` queue alert now respects daylight saving
  time.
- Busy commands have short cooldowns and clearer error messages.

(Maintainer notes: full code review in `docs/CODE_REVIEW_2026-07.md`; this
release lands items #1–#22 and #24 — fixed the broken `test_statistics`
command, removed dead code (`MockSteamAPI`, `NotificationLog`, unused deps),
lazy-imported `formation_optimizer` to keep numpy/matplotlib off the startup
path, deduplicated the Steam sweep with a persistent HTTP session, gated
`!commandlogs` behind `is_owner`, standardized on zoneinfo Pacific time,
switched to a rotating log file, and hardened the A2S rules JSON parser.)

## 2.3.3 — 2026-05-04

- `!nextgame lobby` only pings when a lobby is ready; debrief alerts are
  suppressed. Stacks with `ptb` and `--skip`.

## 2.3.2 — 2026-05-01

- Fixed a rare error that could affect the live server status message right
  after the bot started up.
- Stability improvements.

(Maintainer notes: traced the recurring brief outages to `dnf-makecache`
overrunning available RAM under bot load; disabled and masked. Lazy-loaded
matplotlib + numpy to drop idle RSS by ~80–120 MiB. Fixed a latent
`NameError` in `ServerFormatter.create_status_embed`. Postmortem in
[`docs/OPS.md`](docs/OPS.md).)

## 2.3.1 — 2026-03-03

- Improved `!nextgame` queue handling for standard and PTB modes.
- Added a daily 6pm PST queue-interest alert.
- Sanitized URL-like text in server names for safer alerts.

## 2.3.0 — 2026-01-01

- `!listservers` now includes PTB / test-branch servers by default.
- Live-updating tracked messages respect saved PTB / `all` filters on refresh.
- `!nextgame` supports `--skip` and PTB filtering throughout the notification
  pipeline.
- New `!graph` command renders 7-day graphs (players, servers, lobbies, games)
  from `PlayerSnapshot` data.
- New `!formation` command integrates the standalone formation optimizer:
  compacts fleets and optionally generates GIF animations.
- Command usage is logged via the `CommandLog` model.
- Steam server-rule lookups run off the event loop with timeouts, smoothing
  Discord latency.

## 2.2.0 — 2025-12-26

- Dynamic stable-version detection from the majority of servers.
- PTB / test-branch identification with 🧪 indicator and version display.
- `!nextgame ptb` for PTB-only notifications.
- `!listservers all` to include empty / private / bot-populated servers.

## 2.1.0 — 2025-11-29

- `!graph` command for visualizing player and server data over time.
- `!nextgame` immediately notifies if matching games are already available.
- Notifications grouped by channel to reduce spam.
- `!nextgame` triggers refined: lobby with 3+ players (joinable) or game
  entering debrief.

## 2.0.0 — 2025-11-27

- `!nextgame` notification system.
- Game statistics tracking (`!stats`, `!mapstats`, `!serverstats`).
- Live message updates for server lists.
- Improved multi-server support.

## 1.0.0 — 2025-11-18

- Initial release: real-time server monitoring and basic commands.

---

For deeper historical detail (design docs, migration write-ups, refactoring
notes), see [`docs/archive/`](docs/archive/).

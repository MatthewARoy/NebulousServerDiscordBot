# Changelog

The bot reads its own changelog from `nebulous_bot/config.py` (`Config.CHANGELOG`)
to power the in-Discord `!version` command, so that file is the source of truth
for current and recent releases. This document mirrors it for readers on GitHub.

## 2.7.0 — 2026-08-02

- `!help` is now a proper menu — commands grouped by category, each with
  usage, examples, aliases and cooldowns.
- `!help <command>` and `!help <category>` both work (try `!help nextgame`
  or `!help servers`), and a typo suggests the closest match.
- Maintenance commands are no longer listed in `!help` for anyone but the
  bot owner.

(Maintainer notes: replaces discord.py's `DefaultHelpCommand` with
`nebulous_bot/help_command.py` (`NebulousHelpCommand`), wired in the
`commands.Bot(...)` constructor in `runbot.py`. Pages are generated from the
command docstrings — `parse_help_sections` reads the existing `Usage:` /
`Examples:` / `- !cmd ... - note` conventions, so new commands get help for
free; category emoji and ordering come from `CATEGORY_META`, and an
unlisted cog still renders (last, default emoji). Visibility: hidden
commands are revealed only when `is_owner()` passes, resolved per
invocation in `prepare_help_command` (discord.py hands each invocation its
own `HelpCommand.copy()`, so this is not shared state) and fail-closed if
the owner lookup errors. `send_command_help` now refuses hidden commands
with the same "not found" embed a bogus name gets, and typo suggestions are
drawn from `filter_commands` output only — previously `!help commandlogs`
rendered the owner-only log dump's full help page to anyone who guessed the
name. `!restartmonitor` and `!debugmonitor` gained `hidden=True`; that is a
help-visibility flag only, their `has_permissions(administrator=True)`
checks are unchanged. Docstring parsing and embed chunking are pure
module-scope helpers covered by `nebulous_bot/tests/test_help_formatting.py`
— including gateway-free Bot tests with a stubbed `is_owner` for the
visibility rules.)

## 2.6.1 — 2026-07-28

- Fixed `!serverstats` showing wrong per-server numbers — game counts,
  player-hours, and last-game times now cover each server's full history.
- Servers no longer appear more than once in the `!serverstats` list.

(Maintainer notes: `GameSession` rows were grouped by `(server_id,
server_name)`, but `server_id` is the per-process Steam session steamid —
every server restart opened a fresh bucket, scattering ~20k recorded games
across thousands of stale rows. Now grouped by `server_name` only, with the
per-server player-hours N+1 loop folded into a
`Sum(players_at_start * duration_seconds)` annotation on the same query.)

## 2.6.0 — 2026-07-13

- New `!advice` command — search curated fleet-building tips from the
  community (try `!advice point defense`).
- `!advice tags` lists the searchable topics; every tip credits its author
  with a link to the original message.

(Maintainer notes: first release of the community knowledge base —
`knowledge/entries/*.toml` is the canonical curated corpus (47 entries from
the fleet-building tips thread), loaded at boot by `cogs/advice.py` via the
pure-stdlib `nebulous_bot/knowledge.py`. Pipeline: `scripts/export_thread.py`
dumps any channel/thread over REST, the `curate-advice` skill structures it,
`scripts/export_knowledge.py` generates `advice.json` (for the in-game
shipbuilding mod) and wiki-ready Markdown. Schema is CI-enforced by
`test_knowledge_entries.py`; open curation questions live in
`knowledge/QUESTIONS.md`. Design spec:
`docs/superpowers/specs/2026-07-13-community-knowledge-base-design.md`.
Deploy note: verified `knowledge/` ships automatically — the deploy rsync
copies everything not explicitly excluded and the Dockerfile does
`COPY . .`.)

## 2.5.0 — 2026-07-07

- Internal restructuring for reliability — no visible changes; all commands
  work exactly as before.
- `!help` now groups commands by category.

(Maintainer notes: review item #23 — runbot.py's ~1,900 lines of inline
command closures split into six cogs under `nebulous_bot/cogs/`
(setup, stats, servers, admin, formation, nextgame), one commit each.
Cogs read shared state via `bot.server_monitor` / `bot.formatter` /
`bot.deployment_time`, set by `on_ready`; the eager `formation_optimizer`
import stays on the boot path via a module-scope import of
`cogs.formation` in runbot.py (the 2.3.4 lesson). The !listservers and
!nextgame argument parsers are now pure functions with unit tests. The
command inventory — names, aliases, permissions, cooldowns — was verified
identical to 2.4.1 by registering all cogs and diffing the metadata.)

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

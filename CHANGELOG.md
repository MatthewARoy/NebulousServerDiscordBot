# Changelog

The bot reads its own changelog from `nebulous_bot/config.py` (`Config.CHANGELOG`)
to power the in-Discord `!version` command, so that file is the source of truth
for current and recent releases. This document mirrors it for readers on GitHub.

## 2.9.1 — 2026-08-18

- `!advice` results now show each tip's id, and search matches singular and
  plural alike.
- Advice votes expire after 7 days, and each server has its own share of open
  votes.
- Bugfixes for advice search ranking and vote settling.
- Internal test-harness improvements.

(Maintainer notes on the advice fixes, from the 2026-08-18 review of the
command. Ranking: `knowledge.search` tie-broke on entry id alone, and
community ids (`ca-NNN`) sort ahead of every curated prefix, so an approved
community submission restating a curated entry scored the same and took its
place. In production `!advice fpa` served an unstructured copy of `fb-001`
rather than the curated entry, which is the near-duplicate problem the
`!advice improve` ticket describes, already happening. Ties now break
curated-first, then by id. Recall: `tokenize` folds one trailing 's',
guarded on length so shorthand like `ans` and `vls` survives and on a double
's' so `mass` does not become `mas`. Query and corpus both fold, so an
imperfect stem still matches itself; audited against the full 756-token
corpus vocabulary, every merge it makes is a real singular/plural pair. The
alias expansion needed this too, since it emits the singular "accelerator"
against a corpus that spells "Accelerators". Results now carry their entry
id, which the `!advice remove` help text already promised. User-supplied
text (community rule text, display names) is escaped where it reaches a
markdown-parsed embed value, and the credit label gets a bracket-escaping
pass of its own: discord.py `escape_markdown` leaves bare brackets alone, so
a display name containing "](" could hijack the masked link it sits in.
Curated text contains no markdown, so its rendering is byte-identical.)

(Maintainer notes on the advice voting fixes, same review. Ballot lifecycle:
proposals had no timeout, and voiding one meant deleting the bot's own ballot
message, which needs Manage Messages, so a guild without a moderator could not
clear a dead vote at all and it held a slot in the global 25-ballot budget
forever. Ballots now expire after `BALLOT_TTL_DAYS` (7), swept at boot and
again whenever a proposal finds the budget full, so the budget frees itself
without a background task on the tiny VM. The single cap became two, a
per-guild share of 5 plus the global 25, so one server cannot starve the
others; `!advice pending` now lists only the current guild's ballots, since
jump links into another server go nowhere for anyone reading them. Vote
withdrawal: a tie stays open by design, so a 5-5 ballot sat waiting for an
added reaction that never came. `on_raw_reaction_remove` now re-tallies
through the same path as an added vote, and the `on_ready` reconciliation runs
on every connect instead of once per process, because a reconnect leaves the
same gap a restart does. Re-proposal: the duplicate check runs over
`self.entries`, which keeps tombstoned curated entries, instead of the active
corpus, so a voted-out entry's exact words can no longer be voted back in as
an unstructured `ca-*` copy that has lost its situation, reason, tags and
source. New owner-only `!advice restore <id>` is the way back from a removal
vote, which was otherwise global, permanent and undoable only through
`manage.py shell` on the VM; it moves the removal ballots to `rejected` and
leaves their recorded tallies intact rather than introducing an `overturned`
status, which would need a migration that phase 4 already plans to batch.)

(Maintainer notes: `TEST_COMMAND_BOT_IDS` + `TEST_COMMAND_GUILD_IDS` env
vars, both empty by default and both required (fail closed). When set,
prefix commands from the listed bot user ids are processed instead of
dropped, only inside the listed guilds (the designated test guild is
Davaned's personal server), so the Discord MCP puppet bot can drive
deploy smoke tests; see `docs/DISCORD_TEST_HARNESS.md`. Loop-safe: own
messages and DMs never processed, gate is the pure tested function
`harness_command_allowed`. Production behavior is unchanged until the VM
`.env` opts in.)

## 2.9.0 — 2026-08-18

- `!advice` search understands community shorthand (FPA, GPC, beamstone, ...)
  and flags contested ⚠️ / balance-dependent 🕒 advice.

(Maintainer notes: phase 1 of the KB v2 spec,
`docs/superpowers/specs/2026-08-18-knowledge-base-v2-structured-advice.md`.
New `knowledge/catalog/`: `components.toml` and `hulls.toml` are generated
from the live game content registries by the DevAssistant `gamedata`
command via `NebulousDevAssistant/mcp/catalog_dump.py`; regeneration is
owned and rerun per game patch, procedure in `knowledge/catalog/README.md`.
Hand-curated `aliases.toml` and `classes.toml` overlays are CI-validated
against the generated files. Search expands query tokens through the alias
table, so shorthand scores against the display-name words the corpus
spells out. The loader accepts schema v2 fields, with kind, status, and
patch_sensitive defaulted for legacy entries and no bulk verification
claims; validator tests enforce the enums and resolve scope ids against
the catalog. No entry content changed. The deploy path needed no change:
the rsync is exclude-based and the image is built with `COPY . .`, so
`knowledge/catalog/` ships automatically.)

## 2.8.1 — 2026-08-09

- Bugfix for server count.

(Maintainer notes: two silent upstream regressions — Nebulous server builds
stopped publishing `map` in the A2S rules payload, and servers now demand
the A2S_INFO challenge handshake, which the abandoned python-valve library
predates. `steam_api.py` gained a raw-socket challenge-aware A2S_INFO query
(no new dependency) run in the same worker thread as the rules query; live
map/players/max_players/bots override the Steam listing, rules still win
for the map if it ever returns. Timeouts: 2s per UDP query, 4.5s per-server
guard, 15s sweep cap. Verified live: zero mismatches vs independent probes
across multi-cycle soaks, including through an ERI fleet restart.)

## 2.8.0 — 2026-08-06

- `!advice add <tip>` — propose new advice; 5+ 👍 from the community adds it
  to the knowledge pool, 5+ 👎 marks it incorrect.
- `!advice remove <id>` — vote out advice that turns out to be wrong
  (5+ 👍 removes it).
- `!advice list` — audit the whole knowledge pool by category, including the
  incorrect pool; `!advice pending` shows open votes.

(Maintainer notes: community submissions live in the new `AdviceProposal`
table (migration 0010) — the curated TOML corpus is baked into the Docker
image, so anything added from Discord must live in the DB to survive a
redeploy. Approved add-rows ARE the community entries (`ca-<pk>`), merged
into the search corpus at runtime; approved remove-rows tombstone curated
entries out of search without touching git. Ballots resolve in
`on_raw_reaction_add` — threshold AND strict majority, ties stay open;
votes are tallied per user from the reactions' voter lists so 👍+👎 from
one person cancels out — with an `on_ready` re-tally covering votes cast
while the bot was down and delete-listeners voiding deleted ballots.
Vote-resolution logic is pure (`knowledge.resolve_votes`/`tally_voters`),
tested DB-free in `test_advice_votes.py`. Threshold is
`ADVICE_VOTE_THRESHOLD` (env-overridable, default 5). Design spec:
`docs/superpowers/specs/2026-07-30-advice-community-voting.md`.)

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

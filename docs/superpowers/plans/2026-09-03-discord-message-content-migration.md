# Discord Message Content migration

**Date:** 2026-09-03

**Status:** Track 0 complete; Track 1 ready to implement.

**Development branch:** `claude/discord-intent-denial-f7a07e`

**Track 1 baseline:** `f2ce4a6` (`main` and the development branch are identical)

## Objective

Move all public command interaction to Discord application commands before
Message Content access is removed. Preserve mention-prefixed and DM command
handling as an operational fallback, while avoiding a second parser or a new
runtime service.

Track 1 ends only when the bot has been validated without Message Content in a
test application, the slash command tree has been deliberately synchronized,
and the production bot can reconnect after the privileged intent is disabled.

## Track 0 closeout

- Community collection and processing live in the separate
  `NebulousCommunityResearch` repository.
- Raw and processed Discord research data are absent from this repository.
- Docker build context and Oracle rsync both reject `/research/` and the two
  collector/processor script paths if they are reintroduced accidentally.
- The collector is not running and is not a production-bot responsibility.
- The migration worktree is clean and matches committed `main` at `f2ce4a6`.
- The previous QoL task is idle; Tactical Clarity was completed in its own
  repository and does not share this worktree.
- No production deployment or Discord portal change occurred during Track 0.

## Track 1 scope

### Public slash surface

Expose these 18 top-level entries as hybrid commands during the compatibility
release:

- `status`, `version`
- `formation`
- `nextgame`, `cancelnextgame`
- `listservers`, `openlobbies`, `refresh`
- `setstatuschannel`, `setnotificationchannel`, `setnotificationrole`,
  `removestatus`, `showsetup`
- `stats`, `mapstats`, `serverstats`, `graph`
- `advice`

`advice` becomes a hybrid group whose fallback performs search. Its public
`add` and `remove` subcommands remain guild-only and retain their existing
cooldowns and voting behavior. `advice restore` stays owner-only and must not
appear in the public slash picker.

Keep these mention/DM-prefix-only:

- `restartmonitor`
- `debugmonitor`
- `commandlogs`
- `advice restore`
- the custom help command
- the new owner-only `synccommands` operation

Aliases remain a prefix-side compatibility feature; slash commands use their
canonical names.

### Interaction behavior

- Change the prefix resolver to `commands.when_mentioned_or(...)` before
  disabling Message Content. Ordinary `!` commands remain available only
  during the compatibility release, in DMs, and where Discord provides the
  content exception.
- Give every application command and option a concise Discord-valid
  description.
- Defer any path that can touch the database, wait for the monitor/cache, or
  perform meaningful CPU work before it sends a response.
- Convert interaction-created tracked responses into normal bot-authenticated
  messages before background refreshes. Do not rely on an interaction webhook
  token after its lifetime.
- Centralize user-facing command references and prefer slash-first wording.
- Preserve the current reaction ballot and bot-authored message-edit flows;
  they do not require Message Content.

### Formation boundary

- Accept a typed `discord.Attachment` for slash invocation.
- Bound attachment bytes, XML depth/size, ship count, and socket count before
  optimization.
- Move optimization off the event loop and serialize it globally so concurrent
  users cannot multiply its NumPy/Matplotlib peak.
- Return bounded, user-actionable errors for malformed or oversized fleets.

### Logging and privacy

- Do not create a replacement message-content store.
- Record command name, result, latency, guild/channel identifiers, and only
  explicitly safe structured option metadata.
- Stop retaining raw invocation text in new command-log rows.
- Update privacy and help documentation to describe slash, mention, reply, and
  DM behavior accurately before the production cutoff.

## Implementation slices

Each slice should be a reviewable commit and leave the full suite green.

1. **Runtime contract:** constrain `discord.py` to the tested minor line and
   add gateway-free tests for the intended command tree, descriptions, checks,
   and no-intent bot construction.
2. **Framework:** add `when_mentioned_or`, an owner-only explicit sync command,
   test-guild sync support, and application-command error handling. Never sync
   from `on_ready`.
3. **Low-risk commands:** convert status/version, setup, and cached server
   commands; add deferral and response-parity tests.
4. **Statistics and notifications:** convert stats/graph and nextgame flows;
   make tracked-message editing interaction-safe.
5. **Advice:** introduce the hybrid group fallback and public subcommands while
   preserving ballot authorization and keeping restore prefix-only.
6. **Formation:** add the typed upload path, hostile-input limits, and bounded
   background worker.
7. **Messaging/privacy:** replace hard-coded prefix guidance, update help and
   privacy text, and remove raw command-text logging.
8. **Release A validation:** sync to the test guild, exercise every public
   command with Message Content disabled on the test application, then deploy
   the compatibility release with production Message Content still enabled.
9. **Release B cutoff:** deliberately perform global sync, allow propagation,
   disable Message Content in code and the Developer Portal, restart, and run
   the production smoke/health checks.

## Safety gates

- Work only in the migration worktree; `main` remains the production baseline
  until reviewed commits are intentionally integrated.
- Never deploy from a dirty tree.
- Never synchronize globally as part of startup, tests, or deployment.
- A test-guild sync may happen only through an explicit owner action.
- Global sync and the Developer Portal toggle are separate production actions;
  each requires an explicit go/no-go decision at rollout time.
- Do not remove Message Content before slash parity, test-application
  no-intent validation, and a rollback image are ready.
- Do not mix Track 2 polling/correctness fixes, Track 3 VM work, or new feature
  development into the deadline-critical migration commits.
- Do not copy community-research data, credentials, or tooling into this
  worktree.

## Baseline evidence

At `f2ce4a6`, using a clean isolated dependency environment:

- Ruff: clean.
- Pytest: 188 passed.
- Known warning: `test_formation_visualization` returns `bool` instead of
  asserting; fix it in its own small preparatory commit or alongside the first
  formation test change, not silently inside an unrelated conversion.
- Python 3.11 production baseline and Python 3.12 compatibility smoke both
  passed.

## Track 1 exit checklist

- [x] All 18 public entries and intended advice subcommands are registered.
- [x] Operational commands are absent from the public slash picker.
- [x] No startup path automatically synchronizes the command tree.
- [x] Slow commands defer and tracked responses use bot-authenticated channel messages.
- [x] Formation limits and worker serialization are tested.
- [x] New command logging stores no raw invocation text.
- [x] Help, privacy, deployment, and test-harness documentation are current.
- [x] Full lint and test suites pass on Python 3.11.
- [ ] Test application passes with Message Content disabled.
- [ ] Release A has a verified rollback artifact.
- [ ] Global command propagation is confirmed before the intent cutoff.
- [ ] Production reconnects and passes smoke checks without Message Content.

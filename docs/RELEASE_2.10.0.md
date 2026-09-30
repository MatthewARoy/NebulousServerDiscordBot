# 2.10.0 Discord migration release record

Updated September 30, 2026. **Production migration complete.** Version 2.10.0
serves 19 global slash commands with Message Content, Members and Presence off.
The owner authorized testing and rollout; PR #3 is merged. A fresh gateway
identification after the Portal changes verified operation without privileged
intents. No release announcement has been sent or scheduled.

## Released behavior

- Public commands use canonical slash names. Use `/nextgame`, not `/ng`.
  Legacy aliases still work after a direct bot mention or in DMs; ordinary
  server `!commands` are no longer the supported command surface.
- `/guide` provides the user guide inside Discord, with a private slash response.
  User-facing guidance does not require GitHub or an external document.
- Slow commands defer promptly, errors are bounded, and live list messages use
  bot authentication to continue refreshing after interaction-token expiry.
- Formation uploads have size/XML/depth/radius limits and serialized workers.
- Owner maintenance operations stay out of the public slash picker. Sync is
  manual and guarded, never performed at startup or reconnect.
- One-time next-game subscriptions remain in memory and reset on restart.

## Verification completed

The final source baseline passed **282 tests**, Ruff, Django checks and runtime
imports. CI built and checked the Linux image. The accepted image passed real
entrypoint startup, HTTP health, monitoring and a cold restart in an isolated
intent-off application with a 256 MiB container memory limit.

September 25 live Discord UI acceptance exercised the original 18-command tree,
including valid/malformed fleet uploads, setup persistence, statistics, graph
generation, advice approval/removal and cooldown errors. The final 19-command
tree adds `/guide`, subsequently verified in both test and production. Framework
permission checks passed for all four admin commands.

Packaged Linux tests generated an optimized nine-ship fleet and GIF. Controlled
notification tests used real Discord delivery in the private test server and
covered immediate/delayed delivery, filters, cancellation, duplicate suppression,
configured roles/channels and threshold cooldown.

Production global commands, guide, statistics, graph, immediate next-game ping,
mention fallback and recovered status posts passed. List responses kept updating
over 12 hours after creation. The later host audit found healthy HTTP, zero
automatic restarts/OOMs, no error/traceback/blocked-heartbeat log entries, advancing
statistics, SQLite `quick_check=ok`, and **57 runtime files matching main**.

## Remaining follow-ups

- A repeat production `/formation` upload through Discord's file picker remains
  unverified: the browser tool stalled before submission. Earlier live upload and
  accepted-image optimizer/GIF checks passed. Do not represent the repeat as done.
- A second-account non-admin UI check is optional; framework checks already pass.
- The entrypoint's harmless missing-`pgrep` diagnostic and existing operations
  backlog remain maintenance work, not completed fixes.
- Announcement copy, destinations and timing still need explicit owner approval.
  No deployment or startup automatically sends a notice.

## Operational records

- [Execution record](releases/2.10.0-rollout-result.md): exact artifact, backup,
  deployment times, evidence and limitations.
- [Completed rollout checklist and future release procedure](releases/2.10.0-rollout-plan.md).
- [Announcement review drafts](releases/2.10.0-user-messages.md).
- [Regression test harness](DISCORD_TEST_HARNESS.md) and [operations runbook](OPS.md).

Production pins the verified image; documentation changes do not require a
restart. Version 2.9.1 is not a valid post-cutoff rollback because it requests
Message Content. Repair forward or use a tested intent-off image, preserving the
live database unless an actual data recovery is required. Credentials, raw test
evidence and unrelated fleet-strategy work remain outside this release.

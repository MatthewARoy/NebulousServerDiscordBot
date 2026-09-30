# 2.10.0 Discord migration release record

Owner: current migration task. Updated: 2026-09-30.

**Production cutover completed September 30.** The owner explicitly authorized
testing and rollout. Version 2.10.0 is running with all privileged intents off,
19 global application commands registered, and a fresh post-cutoff gateway
connection. See [the execution record](releases/2.10.0-rollout-result.md) for the
exact artifact, backup, live evidence, and remaining browser-upload check.
Announcements remain unapproved and unsent. The sections below preserve the
September 25 predeployment evidence and original plan; their pending-rollout
statements are historical, superseded by the execution record.

Current operational checklist: [rollout plan and remaining test gates](releases/2.10.0-rollout-plan.md).
Communications are [drafts awaiting owner review](releases/2.10.0-user-messages.md);
nothing is scheduled or sent automatically.

Follow-up: the user guide now ships inside the bot as `/guide` (19th top-level
command). The 18-command live evidence below describes the previous candidate.
Rebuild the image and verify `/guide` registration and its response after copy
approval. User-facing notices contain no repository links or external guide.

## Baselines and boundaries

- Branch: `claude/discord-intent-denial-f7a07e`.
- Migration `c53496e` integrated with `main` `9e7ecab` in `bd25c92`.
- Production was read directly: 2.9.1, Python 3.11.16, discord.py 2.7.1;
  container healthy. No production deployment or global sync yet.
- Developer Portal explicitly reports a September 30 privileged-intent
  deadline; production requests Message Content, not Members or Presence.
- Separate test app: Nebulous Migration Test, installed only in the owner's
  test server. Application/guild/message identifiers and raw acceptance
  evidence are retained in the ignored local `.migration-test/` directory.
  Production Discord credentials and database must never run the test instance.
- Uncommitted fleet-strategy work in the main checkout is outside this release.

## Automated evidence

- Python 3.11.15: 278 tests passed; Ruff passed. The previous 274-test
  baseline also passed on Python 3.12.14.
- Integrated baseline Django system check and runtime imports passed.
- Formation visualization now asserts success instead of silently returning
  a boolean to pytest.
- Production entrypoint can disable all privileged intents through
  `DISCORD_MESSAGE_CONTENT=false`; explicit local CLI override retained.
- Deployment rejects dirty trees, excludes virtual environments/test data/
  local credentials, retains the running image, and takes a consistent
  SQLite backup with an integrity check.
- SQLite backup smoke test passed with committed data in an active WAL,
  verified integrity, and verified refusal to overwrite an existing backup.
- All four admin slash commands reject a non-admin and accept an admin
  through discord.py's actual hybrid permission-check path; denied errors
  use ephemeral responses.
- CI builds a Linux image from the exact candidate commit, checks packaged
  runtime imports and database migrations without network access, and exports
  its image ID, source revision and SHA-256 checksum as a seven-day artifact.
- [CI run 36195089189](https://github.com/MatthewARoy/NebulousServerDiscordBot/actions/runs/36195089189)
  passed for runtime candidate `c25c29a`. Its downloaded Linux/amd64 image,
  source revision and checksum were verified; the rollout plan records them.
  Live packaged startup and notification delivery remain explicit gates.

## Live acceptance

Verified September 25 with Python 3.11.15 and discord.py 2.7.1. Message Content,
Members and Presence were disabled in both the test application's Portal
configuration and the running client.

- Owner-only guild sync registered all 18 top-level commands, including all
  five public advice subcommands. Global command count remained zero.
- Every top-level public command was exercised through Discord's real slash
  UI. Setup channel/role selection and removal persisted in the isolated DB.
- Statistics returned both clean empty-history results and, after a real game
  ended, populated game/map/server results. Graph generation returned an image;
  an immediate repeat produced an ephemeral cooldown error.
- A nine-ship sample fleet returned its optimized file and animated preview.
  Malformed XML returned a bounded, useful error. Size/depth/radius limits and
  cancellation-safe optimizer serialization are covered by automated tests;
  they were not each separately uploaded through Discord.
- Advice search, pending and audit worked. A new proposal was approved by
  reaction, then removed by a second reaction ballot. The removal survived
  restart. The test threshold was one vote; production configuration is unchanged.
- `/listservers`: created 20:54:26 UTC, edited 21:26:48 UTC (32 minutes later).
  `/openlobbies`: created 20:55:04 UTC, edited 21:26:48 UTC (31 minutes later).
  Both updates occurred after interaction-token expiry, using bot-authenticated
  channel messages.
- Mention-prefixed help and `!version` in a direct message both worked without
  Message Content. Command logs retained command identity, not raw argument text.
- Controlled process restart at 21:29 UTC reconnected, resumed monitoring,
  loaded the existing advice verdict, and preserved server setup. Subsequent
  slash commands succeeded without re-syncing the command tree.

Limitations: non-admin denial was verified through framework tests, since the
test server has only its owner. Waitlist subscribe/cancel passed; actual future
threshold notification delivery was not forced. Production rollout is pending.

Launch using the verified Python environment:

```powershell
.venv-release/Scripts/python scripts/run_migration_test.py --credentials <local-test-env> --production-env <local-production-env> --guild <test-guild-id>
```

The launcher reads only the Steam key from production into the child,
verifies distinct application/token identity via Discord, requires the test
app to belong only to the selected guild, creates an isolated test database,
disables every privileged intent, and does not sync commands automatically.
The full acceptance matrix is in [DISCORD_TEST_HARNESS.md](DISCORD_TEST_HARNESS.md).

## Production go/no-go

1. Record the exact accepted commit and immutable image ID; preserve the
   current image, Compose configuration, environment, and verified database backup.
2. Deploy compatibility image with Message Content still enabled; check
   gateway connection, monitoring, health, mentions and fallback.
3. Deliberately sync the production global tree, then verify slash commands
   in the production application's test-server installation.
4. Set `DISCORD_MESSAGE_CONTENT=false`, recreate the container, and verify
   connection/monitoring/slash/mention behavior. Disable the Portal toggle.
5. Confirm a subsequent reconnect with no privileged intents requested.

Keep these stages separately observable. Never infer live acceptance from
unit tests or claim completion from a container's HTTP health alone.
The old 2.9.1 image cannot survive a revoked Message Content intent; after
cutoff, rollback must preserve an intent-off runtime.

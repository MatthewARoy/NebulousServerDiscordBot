---
name: release
description: Cut a new bot version — bump Config.VERSION, update both changelogs (Config.CHANGELOG and CHANGELOG.md), and hand off to the Oracle deploy. Use when the user asks to release, ship, bump the version, or deploy.
---

# Releasing a new bot version

Versioning is user-facing: the bot serves its own changelog via `!version`,
so a release is not done until **both** changelog locations are updated.

## Steps

1. **Pick the version** (semver-ish): patch for fixes, minor for new
   commands/options. Current version lives in `nebulous_bot/config.py`
   (`Config.VERSION`).

2. **Update `nebulous_bot/config.py`:**
   - Bump `Config.VERSION`.
   - Prepend a new entry to `Config.CHANGELOG` (list is newest-first):
     `{"version": ..., "date": "YYYY-MM-DD", "changes": [...]}`.
   - Write changes in player-facing language (they render in Discord embeds;
     the `!version` embed shows only the first 2 changes per entry, so lead
     with the most important).
   - **Never put technical/implementation notes in the patch notes** — they
     are reserved for features. Bugfixes get one super-simple line (e.g.
     "Bugfix for server count"); mechanism, root cause, and internals go in
     the `CHANGELOG.md` maintainer-notes block only.

3. **Mirror to `CHANGELOG.md`** at the repo root — same content, markdown
   format, newest-first. `Config.CHANGELOG` is the source of truth;
   `CHANGELOG.md` mirrors it for GitHub readers. Maintainer-only notes
   (ops, internals) go in italic "(Maintainer notes: ...)" blocks in
   `CHANGELOG.md` only — don't ship internals to the Discord embed.

4. **Run the verify loop** (`.claude/skills/verify/SKILL.md`), then commit.

5. **Deploy**: the user runs this themselves. It needs their SSH key and the
   VM address from the gitignored `ORACLE_CONNECT.md`. The script ships CI's
   verified image artifact, never source, and dry-runs by default:
   ```
   gh run download <run-id> -n nebulous-bot-image -D <dir>
   OCI_VM_HOST=<vm> ./deployment/oracle/deploy-to-oracle.sh --image-dir <dir>         # dry run
   OCI_VM_HOST=<vm> ./deployment/oracle/deploy-to-oracle.sh --image-dir <dir> --live
   ```
   It stamps `DEPLOYMENT_TIME` itself. Run the isolated acceptance in
   `docs/releases/` first. Remind the user; do not attempt the deploy
   yourself unless they have explicitly asked for it.

6. **Post-deploy check**: `!version` in Discord should show the new number;
   `!status` should show monitoring running.

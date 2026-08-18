# KB v2 Phase 1 (Foundation): implementation plan

**Date:** 2026-08-18
**Spec:** `docs/superpowers/specs/2026-08-18-knowledge-base-v2-structured-advice.md`
(phases section). Phase 1 is compatibility only: catalog + aliases + schema
acceptance. No entry content edits, no triggers, no voting changes. The only
user-visible behavior change is better search recall and status badges.

## Work items, in order

1. **Catalog generation (outside this repo, output committed here).**
   Produce `knowledge/catalog/components.toml` and `hulls.toml`: every
   hull/component ID in fleet-XML form, display name, hull `faction`. Each
   file header records `catalog_version` (game version), the generation
   command, and the date. Mechanism to settle first in-session: check
   whether a DevAssistant command can dump the component/hull registries
   (preferred; the workspace toolkit auto-discovers mod commands), else a
   decompile-driven script in the NebulousDevAssistant/mapgen tooling. Add
   `knowledge/catalog/README.md` documenting the regeneration procedure and
   its owner (rerun per game patch).
2. **Hand-curated overlays.** `knowledge/catalog/aliases.toml` seeded with
   community shorthand already appearing in the corpus and the counters
   thread (FPA, RCC, ARR, SRA, GPC, RDC/DCX, mk600, beamstone, hull
   nicknames). `knowledge/catalog/classes.toml` with the classes the
   existing 47 entries need (`beam-weapons`, `chaff-launchers`, `antennas`,
   `acceleration-drives`, others as encountered).
3. **Loader + search.** `nebulous_bot/knowledge.py`: load catalog and
   overlays (stdlib tomllib, same failure-tolerant pattern as
   `load_entries`); expand query tokens through aliases in the scorer so
   "FPA" hits fb-001. Pure-logic tests alongside the existing search tests.
4. **Schema v2 acceptance.** Extend `test_knowledge_entries.py` validation:
   new optional fields (`kind`, `status`, `patch_sensitive`, `verified`,
   `verified_version`, `exceptions`, `[entry.scope]`) with enum checks and
   scope IDs validated against the catalog. Loader defaults for legacy
   entries: `kind=rule`, `status=established`, `patch_sensitive=false`, no
   verified claim.
5. **`!advice` badges.** Render ⚠️ (contested) / 🕒 (patch-sensitive) in
   result embeds. Cog-level change, small.
6. **Deploy + release.** Add `knowledge/catalog/` to the rsync includes in
   `deployment/oracle/deploy-to-oracle.sh`; version bump + both changelogs
   via the release skill (patch-notes-features-only rule: one simple line,
   e.g. advice search understands community shorthand).
7. **Verify.** The verify skill end-to-end (ruff, pytest, `manage.py
   check`, import smoke test) before commit.

## Constraints that bite here

- Bot loads everything eagerly at boot; catalog is a few hundred KiB of
  TOML, fine. No new dependencies.
- Tests stay DB-free and pure-logic (construct via `__new__`).
- `AGENTS.md` mirror rule does not apply (workspace-level file untouched).

## Explicitly not in phase 1

Entry enrichment (phase 2), trigger evaluator and `!fleetcheck` (phase 3),
DB migrations and modal intake (phase 4), anatomy files (phase 5).

## Session kickoff prompt

Paste this to start the implementation session. If the catalog dump needs
DevAssistant, start the session from the workspace root or the bot repo
(not the worktree path) so it can reach both.

```text
Implement Phase 1 (Foundation) of the Knowledge Base v2 design for the
Nebulous Discord bot.

Context to load first:
- Branch: claude/nfc-knowledge-base-d98a97. Continue on this branch; do
  not merge to main.
- Plan (your task list, follow its 7 work items in order):
  docs/superpowers/plans/2026-08-18-kb-v2-phase1-foundation.md
- Spec (the why; sections 1-2 matter most for this phase):
  docs/superpowers/specs/2026-08-18-knowledge-base-v2-structured-advice.md

Scope: phase 1 is compatibility only. Catalog generation + hand-curated
alias/class overlays, alias-fed search in nebulous_bot/knowledge.py,
schema v2 fields accepted by loader and validator tests with safe legacy
defaults, status badges in !advice, deploy-script rsync include for
knowledge/catalog/, version bump. No entry content edits, no triggers,
no DB changes, no voting changes.

First decision to settle: the catalog dump mechanism. Check whether a
NebulousDevAssistant command can dump the hull/component registries
(devcli.py commands, or the commands.json manifest; the game must be
running with DevAssistant enabled, and you have autonomy to launch/kill
it). If not, write a decompile-driven generator in the workspace tooling.
Either way the committed output is knowledge/catalog/components.toml and
hulls.toml with catalog_version, generation command, and date in the
header, plus a knowledge/catalog/README.md documenting regeneration.

House rules that bite here: no new dependencies (tomllib only), tests
stay pure-logic and DB-free (construct via __new__), eager loading at
boot, version bump updates both Config.CHANGELOG and CHANGELOG.md
(patch notes are features-only, one simple line). Run the verify skill
before each commit. Any docs you write: plain prose, no em dashes.
Commit when verified; I run deploys myself.
```

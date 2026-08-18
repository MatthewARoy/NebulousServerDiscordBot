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

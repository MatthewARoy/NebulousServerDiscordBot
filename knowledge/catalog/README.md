# Knowledge catalog

Game truth and vocabulary for the knowledge base (see
`docs/superpowers/specs/2026-08-18-knowledge-base-v2-structured-advice.md`,
section 1). Two kinds of file live here and they have opposite editing rules.

## Generated files (never hand-edit)

- `components.toml`: every component and munition save key the game
  registers, in the exact form fleet XML uses, with a display name.
- `hulls.toml`: every hull save key with display name, in-game class name
  ("Moorline", "Axford") and faction (`ans`, `osp`, `civilian`).

Each file header records `catalog_version` (the game build it was dumped
from), the generation date, and the generation command. Output is sorted,
so a regeneration diffs cleanly: that diff is the mechanical change list
the patch-triage workflow starts from.

### Regeneration procedure (rerun after every game patch)

Owner: Davaned. A stale catalog is the main failure mode of this design,
so regeneration is part of picking up a game patch, not an optional chore.

1. Extract the installed stock bundles with
   `NebulousDevAssistant/mcp/offline_gamedata/` (see its README). Pin the
   game version/build used for extraction. This does not require running
   or interrupting the game.
2. From the workspace root, run:

   ```
   python NebulousDevAssistant/mcp/catalog_dump.py --out <this repo>/knowledge/catalog --offline-full <dump-dir>/gamedata_full.json --game-version <version-and-build>
   ```

   The script records the input SHA-256 and uses the asset/prefab names
   assigned by `BundleManager.LoadMunitionEntries`. Save-key suffixes are
   not always display names: `Stock/Flak Round` displays as `50mm Flak Shell`.
   Hull class/faction membership comes from the serialized hull definitions.
3. Review the diff (new, removed, renamed content), run the test suite
   (it validates that the hand-curated overlays below still resolve
   against the regenerated files), and commit.

The legacy `--from-json <saved gamedata response>` and live mode (omit both
source options) remain available. Those registry responses lack munition
display names, so their labels fall back to save-key suffixes; prefer the
offline mode for the corrected catalog. Live mode requires an already-running
game with DevAssistant and reads its version from Player.log unless overridden.

## Hand-curated overlays (regeneration never touches these)

- `aliases.toml`: community shorthand mapped to catalog ids ("FPA",
  "beamstone"). Feeds search: a query token matching an alias also
  searches the words of the target's display name.
- `classes.toml`: named component sets that advice speaks in
  (`class:beam-weapons`). Membership is editorial judgment, not a data
  dump.

Both files are validated in CI against the generated catalog: alias names
must be unique and their targets must resolve; class names must be unique
and every member must resolve. Add entries in the same commit that first
needs them.

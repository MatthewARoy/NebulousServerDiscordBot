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

1. Launch NEBULOUS with the DevAssistant mod enabled (workspace repo
   `NebulousDevAssistant`, `build/publish.ps1 -Enable`). Wait for the main
   menu.
2. From the workspace root, run:

   ```
   python NebulousDevAssistant/mcp/catalog_dump.py --out <this repo>/knowledge/catalog
   ```

   The script drives the in-game `gamedata` command over the DevAssistant
   file bus and reads the game version from Player.log.
3. Review the diff (new, removed, renamed content), run the test suite
   (it validates that the hand-curated overlays below still resolve
   against the regenerated files), and commit.

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

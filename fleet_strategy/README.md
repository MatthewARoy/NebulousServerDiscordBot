# Fleet strategy module

Portable shipbuilding knowledge, design planning, and advisory review for
NEBULOUS team PvP. Python 3.11+, standard library only. Importing this package
does not load Django, Discord, numpy, a database, or the game.

The canonical data lives in `knowledge/strategy/`, with source advice in
`knowledge/entries/` and game identities in `knowledge/catalog/`. Keeping
these in the bot repository avoids a second copy of the advice. The package
has no import dependency on the bot and accepts an explicit knowledge path.

## API

```python
from pathlib import Path
from fleet_strategy import load_bundle, load_geometry, parse_design, review_fleet
from fleet_strategy import evaluate_stack, overlay_projection
from fleet_strategy.planning import plan_design

bundle = load_bundle(Path("knowledge"))
snapshot = parse_design(Path("example.fleet").read_bytes())  # also .ship
report = review_fleet(snapshot, bundle, role="frontline")
# Without geometry, fitting advice is available and protection is unknown.

geometry = load_geometry("staging/fleet_geometry.json")  # optional, private local data
report = review_fleet(snapshot, bundle, geometry=geometry,
                      protection_threat="hei", protection_direction="bow")
assessment = report["protection"]
colors = overlay_projection(
    assessment, build_id=assessment["build_id"], geometry_id=geometry["geometry_id"],
    bundle_id=bundle["bundle_id"], threat_id="hei", direction="bow",
)

# Exact keys from the parsed ship: caller ASSUMES these share one HEI ray.
scenario = evaluate_stack(snapshot, bundle, ship_key="ship-1",
                          socket_keys=["SocketA", "SocketB"],
                          threat_id="hei", damage_reduction=0.2)

brief = plan_design(
    bundle, scope="ship", faction="ans", role="denial", budget=650,
    investment="lean", targets=["capture ships"],
    support=["friendly scout supplies a firing solution"],
)
```

Public inputs and outputs are JSON-compatible dictionaries. `parse_design`
accepts a saved `<Fleet>` or `<Ship>` document. `parse_fleet` remains available
for consumers requiring a fleet specifically. Parsing never mutates a save.

`role` is an explicit review lens, not a classification inferred from a name.
For a mixed fleet, review individual ships separately to describe their roles
and deliberate lean-investment exceptions precisely. A lean/cringed setting
does not erase weapon prerequisites.

## CLI

Run from the repository root, or supply an explicit `--knowledge` path:

```text
python -m fleet_strategy review example.fleet --role frontline
python -m fleet_strategy review example.ship --role denial --investment lean
python -m fleet_strategy review example.fleet --geometry staging/fleet_geometry.json --threat 450-ap --direction port
python -m fleet_strategy review example.ship --stack ship-1:SocketA,SocketB --threat hei --dr 0.2
python -m fleet_strategy plan --scope fleet --faction osp --role skirmish --budget 3000
python -m fleet_strategy plan --scope ship --faction ans --role denial --budget 650 --investment lean --template example.ship
python -m fleet_strategy export --out knowledge/exports/strategy-bundle.json
```

`--threat` alone selects the automatic assessment profile; the default is
`hei` from `bow`. Directions are `bow`, `stern`, `port`, `starboard`, `top`
and `bottom`. A manual `--stack` scenario instead requires `--threat` and
`--dr` together. Automatic review derives its conditional DR from supported
stock hull statistics and socket occupancy; manual scenarios use supplied DR.

The plan contains an explicit brief, build sequence, role questions, layout
concepts, and relevant reference examples. Supplied ship templates are
faction-compatible reference candidates; the planner does not rank their
combat quality, assume their saved costs are current, or fit components.

## Consumer contract

`schema_version = 1` is this module's bundle/report schema. It is separate
from the older advice export schema. The single exported JSON contains the
strategy, source entries, identity catalog, checks, pinned damage model, catalog version, and a
SHA-256 content identity. It avoids mismatched advice/catalog files and is
the proposed Drydock input. No Python runtime is required to read it in C#.
Geometry has its own schema and content identity and is installed separately;
it is not included in this portable bundle.

A C# evaluator must implement the same predicate semantics and pass the
shared conformance cases before applying checks in Drydock. Future editor
changes should operate on the live ship through game APIs, with a preview
and undo. Neither this package nor the bot writes fleet XML.

Consumers must supply their current removed-advice IDs through
`excluded_entry_ids`. The Discord adapter reads the Advice cog's tombstones.
A standalone bundle does not contain the live Discord moderation database.
Independent protection arithmetic remains available when the bot cannot
check moderation state; community advice is withheld in that case.

## Current coverage

Five source-linked checks cover insufficient beam FPAs, a beam ship's
onboard/shared fire-control dependency, missing gun plotting support, and
missing loaded 450mm HE/AP for the initial supported cannon set. Unknown
content and skipped checks are reported; zero findings is not a quality
verdict. Unloaded missile templates never count as ammunition.

Detailed guidance covers hull layout, reinforced stacks, deliberate cringing,
support, cost tradeoffs and seven roles. The optional geometry assessment
returns per-ship/socket regions, worst sampled packet, DT margin, supporting
recipients and their vulnerability, individual probes and unknown coverage.
It uses five deterministic probes per target from one selected direction;
this is not a complete attack envelope or combat survival probability.

The current private cache supports conditional **HEI and 450 mm AP ray**
assessments. These rays begin at an assumed enclosing-box entry, not a solved
armor surface. HEI uses the maximum stock ray packet; AP uses its first
recipient behavior. The shared code also contains an HE sphere sampler, but
the generated cache does not establish the completeness of the engine's
20-slot, all-layer overlap query. Consequently 120/250/450 mm HE automatic
assessments remain unknown with this cache. HE, HE-SH, rail and fracturing
are still usable in explicit manual packet scenarios.

Ray queries also withhold results at 20 raw collider hits. Structural hits
count toward that buffer before recipient filtering, but do not increase
the component-sharing divisor. Origins inside approximate colliders also
yield unknown coverage.

Candidate suggestions add one empty Reinforced Magazine in a compatible
vacant socket, compare sampled target margins, and check the added part's
own probes. Candidates whose added part or improved targets rely on
vulnerable or unknown supporting recipients are withheld. This is a bounded
search, not an optimal-stack generator. It
does not replace equipment, change ammunition, apply edits or recalculate
final cost, mass, crew/resources and capacity. A suggested improvement can
still leave a target above DT; inspect the actual before/after margins.

`evaluate_stack` separately calculates packets for the caller's entire
ordered, non-destroyed hit collection and supplied DR. Source values and
assumptions travel in `damage_model`; results retain bundle identity and
the pinned game version. In this explicit calculator, blue means every
selected recipient is within DT under the supplied assumptions, amber
exceeds DT, and grey is unknown. HP loss and disabled
functions remain possible. Missing, unsupported or mismatched data never
becomes a protection guarantee.

The eight profiles distinguish HEI and HE-SH rays, HE explosion pools, AP first
hits, rail falloff, and fracturing direct rays. Rail and fracturing bypass DR.
For even splitting, the weakest-recipient pool budget is `N * min(DT)`, not a
sum of thresholds. This does not infer physical stack geometry, simulate HP
loss, or certify immunity. `destruction_gate` is a separate pure helper for
strict DT and committed-health rules, not a health simulation in fleet review.

`overlay_projection` supplies keyed color/status rows and clears stale
colors, margins and supporting sockets when build, geometry, bundle, threat
or direction differs, or the assessment's engine version differs from
`ENGINE_VERSION`. Parsed build identity incorporates the complete input XML
hash, so any XML-byte change invalidates a prior projection. The caller
must supply current identities and trigger
recomputation. This is a presentation helper, not a running Drydock overlay:
live game data, editor events, rendering and C# conformance remain to be
implemented and tested. Full packet/DT/probe details remain in the assessment.

Projection colors account for support: blue requires the target and known
supporting recipients within DT on five assumed samples; amber means the
target or supporting recipients exceed DT; grey means unknown, incomplete
or stale evidence. A target's `within-dt` status is preserved when vulnerable
support makes its color amber or unknown support makes it grey. Status and
color therefore serve different purposes and must be displayed with context.

## Local geometry setup

For maintainers with the pinned **0.6.2.6 public, Steam build 25104609** stock
bundles, `scripts/build_fleet_geometry.py` reads local assets with the
developer-only `UnityPy==1.25.3` dependency:

```text
python scripts/build_fleet_geometry.py --bundles <game>/Assets/AssetBundles --out staging/fleet_geometry.json
```

The exporter verifies pinned bundle hashes; changed game data requires a
new audit. Runtime bot dependencies remain unchanged. Generated geometry is
private local cache: `staging/` is ignored by Git and Docker, and the cache
must not be committed or redistributed with the public repository.

The CLI reads `--geometry`; the bot reads optional `FLEET_GEOMETRY_PATH` at
cog initialization. Provision that file separately and restart after updates.
Missing/invalid geometry, unsupported modular layouts and version mismatches
remain unknown. The geometry code samples colliders; it does not solve armor,
penetration/overpenetration, damage progression, repairs or continued function.

See [the engineering outline](../docs/STRATEGY_MODULE.md) for the evidence
boundaries, supported use cases, and next integration steps.

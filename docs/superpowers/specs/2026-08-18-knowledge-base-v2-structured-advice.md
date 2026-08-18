# Knowledge Base v2: Structured, Triggerable Community Advice

**Date:** 2026-08-18
**Status:** Direction agreed in discussion; Codex-reviewed; not yet implemented
**Discussion outcomes:** The user is Davaned, so the Drydock mod is a
first-party consumer. (a) Repo split deferred. (b) Contribution stays
free-text, with optional structured hints (6a), not validated forms.
(c) `!fleetcheck` confirmed as the proof consumer. (d) Staleness handled by
patch-notes triage (6b). Curator review happens in Discord or a review
sheet, never in git (6c); git stores the canon but is not a review surface.
Fleet archetypes added as a taxonomy layer (5), with counter relations;
seed thread 1461715057166651637 exported to `knowledge/raw/`.
**Review:** Codex review 2026-08-18 (17 findings) folded in. The largest
changes: promoted entries keep their `ca-*` id forever, tombstones are
permanent, confidence and staleness are separate fields, anatomy geometry
is separated from survivability claims, counter relations are stored one
direction only, the cross-language trigger contract gets conformance
fixtures, `!fleetcheck` input handling is hardened, and phasing was
resequenced (enrichment is its own judgment phase, deploy changes are
called out per phase).
**Builds on:** `2026-07-13-community-knowledge-base-design.md` (curated TOML
corpus + `!advice`) and `2026-07-30-advice-community-voting.md` (community
👍/👎 additions/removals).

## Problem

The v1 knowledge base proved the pipeline (Discord thread → curation → TOML →
`!advice` search → `advice.json` export). Three requirements now exceed it:

1. **Machine-triggerable advice.** "This ship has a beam and no FPA" should
   fire fb-001 automatically: in a fleet-check command now, in an in-game
   drydock editor later. The v1 `situation` field is prose; nothing can
   evaluate it against a fleet file.
2. **Hull-anatomy knowledge.** "The Vauxhall's nose stack is a good spot for
   reinforced components; the central body is very vulnerable" describes a
   hull. It is not a Situation/Rule/Reason tip, has no home in the v1 schema,
   and is exactly what a drydock editor wants to show per socket.
3. **Weak tagging and search.** Searching "FPA" finds nothing because the
   corpus says "Focused Particle Accelerators". Tags are a flat topical list
   with no record of which hull or component an entry applies to.

The standing goals remain: community members contribute and vet advice with
low friction, and the corpus stays consumable by future clients (drydock
editor, wiki, other mods) without new engineering.

## Constraints (inherited, restated)

- Production VM has ~503 MiB usable RAM. No embeddings, no vector search, no
  runtime LLM calls, no new heavy dependencies. `tomllib` remains the only
  format machinery in the bot.
- The bot is stable. Every change must be small and independently verifiable;
  tests stay pure-logic and DB-free.
- Curation quality over automation: every canonical entry passes human review
  before it lands. Review happens where curators are (Discord ballots, a
  shared review sheet), not in git. Git stores the canon and its history;
  applying reviewed decisions to the TOML files is mechanical.

## Design overview

Separate three layers that v1 conflates:

```
knowledge/catalog/   game truth + vocabulary: hull/component IDs, classes, aliases, archetypes
knowledge/entries/   human knowledge: rules, concepts, anatomy notes            (curated canon)
        └─ [entry.trigger]  machine layer: declarative predicates on a fleet    (optional per entry)
```

Prose is for humans and never needs to be parseable. Triggers are data (a
closed predicate vocabulary), never code, so the Python bot and a C# mod
evaluate the same `advice.json` and reach the same verdicts. The catalog is
the prerequisite for everything else: without canonical IDs and named
classes, trigger predicates cannot be CI-validated and typos rot silently.

### 1. Catalog: `knowledge/catalog/`

Generated files (regenerated per game patch, never hand-edited):

- **`components.toml` / `hulls.toml`.** Every hull and component ID in the
  exact form fleet XML uses (`Stock/Mk600 Beam Cannon`, `Stock/Vauxhall
  Light Cruiser`; confirmed against `formation_optimizer/tests/data/*.fleet`),
  plus display name. Hull records carry `faction` (this is what
  `faction_is` derives from) and basic class metadata. Each file header
  records `catalog_version` (the game version it was dumped from), the
  generation command, and the date, so regeneration is reproducible and
  staleness is visible. Generation source: the NEBULOUS dev toolchain in
  the workspace (decompile or a DevAssistant command dumping the
  registries). Regeneration needs an owner per game patch; a stale catalog
  is the main failure mode of this design.

Hand-curated files (regeneration never touches them):

- **`aliases.toml`.** Community shorthand mapped to catalog IDs ("FPA",
  "mk600", "beamstone"). Kept separate from the generated files precisely
  so a catalog regeneration cannot erase editorial work.

  ```toml
  [[alias]]
  id = "Stock/Focused Particle Accelerator"
  names = ["FPA"]
  ```

- **`classes.toml`.** Named component sets that advice speaks in:
  `class:beam-weapons`, `class:chaff-launchers`, `class:antennas`,
  `class:acceleration-drives`. Hand-curated because "what counts as a beam
  weapon for this advice" is a judgment call, not a data dump.

  ```toml
  [[class]]
  name = "beam-weapons"
  members = ["Stock/Mk600 Beam Cannon", "Stock/Mk610 Beam Turret"]
  ```

- **`archetypes.toml`.** Fleet-level taxonomy (section 5).

CI validation across the combined namespace: IDs, class members, and alias
targets unique and resolvable; every class member and alias target exists
in the generated catalog.

Unknown IDs are a normal condition, not an error: fleet files can contain
modded content the catalog has never seen. Trigger evaluation treats an
unknown component as absent (it can never fire a finding), and
`!fleetcheck` lists unrecognized IDs separately so the omission is visible.

The catalog pays off before triggers exist: feeding aliases into the
existing search scorer (`nebulous_bot/knowledge.py`) as synonym expansion
makes "FPA" match fb-001 with no other changes. That fixes most of the
search problem on its own.

### 2. Entry schema v2: `knowledge/entries/`

All v1 fields stay. Additions are optional, so old entries load unchanged:

```toml
[[entry]]
id = "fb-001"
kind = "rule"                 # NEW: rule | concept | anatomy (default: rule)
situation = "Fitting the ANS Mk600 Beam Cannon or Mk610 Beam Turret"
rule = "Take at least 2 Focused Particle Accelerators with ANS beam weapons"
reason = "Beams deal many small ticks; FPAs push each tick over the reinforced-component threshold"
exceptions = ""               # NEW: prose caveats (fb-037's Grazer+Aurora combo, fb-045's 3kBB fleets)
tags = ["beams", "modules", "ans"]
status = "established"        # NEW: confidence: established | contested
patch_sensitive = false       # NEW: staleness risk flag, separate from confidence
verified = 2026-08-18         # NEW: last date a human confirmed it against live balance
verified_version = "0.4.1.2"  # NEW: the game version it was confirmed against
author = "Davaned"
source_url = "https://discord.com/channels/..."
curated = 2026-07-13

[entry.scope]                 # NEW: structured applicability (all optional)
factions = ["ans"]
hulls = []                    # catalog hull IDs; empty = any
components = ["class:beam-weapons"]
archetypes = []               # archetype ids (section 5); empty = any

[entry.trigger]               # NEW: machine predicate (see 3); many entries won't have one
severity = "warn"
when = [
  { has = "class:beam-weapons" },
  { count_lt = { component = "Stock/Focused Particle Accelerator", n = 2 } },
]
```

- **`kind`** separates prescriptive rules from explainer concepts ("how chaff
  works", "layered missile defense") and hull anatomy claims (section 4).
  Concepts cover the general chaff / missile-defense advice: longer-form,
  tag-searchable, never triggered.
- **Confidence and staleness are separate fields.** An entry can be both
  contested and patch-sensitive; one enum cannot say that. `status` records
  community confidence (`contested` marks live disagreement, fb-031 and
  fb-047, without hiding the entry). `patch_sensitive` flags entries whose
  truth rides on current balance; QUESTIONS.md already carries four
  "currently useless" claims (fb-008/009/041, the Grazer) that any patch
  could flip. `verified` + `verified_version` record when and against which
  game build a human last confirmed the entry. Legacy entries default to
  `status = "established"`, `patch_sensitive = false`, and no verified
  claim; fresh verification is asserted entry by entry, never in bulk.
- **`scope` is browse/filter metadata, never an evaluated predicate.**
  Automatic findings require a trigger. Filter semantics are fixed: values
  within a dimension are ANY, dimensions combine as AND. Scope values are
  CI-validated against the catalog, so unknown IDs cannot reach runtime.
- **`exceptions`** moves caveats out of the `reason` field (fb-037 keeps one
  there today) and documents why trigger severity is never "error".

### 3. Trigger layer: declarative predicates

The vocabulary is provisional until a **capability matrix** exists: phase 3
starts by classifying all 47 entries by what their condition actually needs
(mounted components, ammunition, socket size, built-in hull equipment,
fleet-level composition, exclusions). The vocabulary grows only where the
matrix shows demand; entries whose conditions do not fit stay prose-only.
That is a feature: a small vocabulary two languages implement identically
beats an expressive one they implement differently.

Starting vocabulary, ANDed within `when`:

| Predicate | Meaning (evaluated per ship against its fleet XML) |
|---|---|
| `has = X` | ship mounts at least one of component/class X |
| `missing = X` | ship mounts none of X |
| `count_lt = {component, n}` / `count_gte = {component, n}` | mount-count threshold |
| `hull_in = [...]` | ship's `HullType` is one of these |
| `faction_is = "ans" \| "osp"` | from the hull's catalog faction |
| `in_region = {region, component}` | X is socketed in a named hull region (4); needs anatomy data |

OR across components is normally expressed through classes. If the matrix
shows conditions that classes cannot express, the vocabulary gains an
explicit `any_of` block then, not speculatively.

`severity` is `warn` or `info` only. Advice is advisory by design; the
exceptions field exists because good fleets sometimes break rules.

**The cross-language contract is conformance fixtures, not prose.** A
committed set of test vectors (fleet input + the exact entry IDs expected
to fire) defines evaluator behavior; the Python evaluator and any C#
implementation must pass the same fixtures. Edge behavior is fail-closed:
an unknown predicate, an unresolvable ID, or a schema version the evaluator
does not know skips that entry and logs, and never produces a finding.
Evaluation is about 50 lines of dict-driven pure Python, no eval.

### 4. Anatomy layer: geometry and claims, separated

Two different kinds of information, stored separately:

**Geometry** lives in `knowledge/hulls/*.toml`: named regions mapped to
socket keys. This is game truth like the catalog (verifiable from game
data), carries no opinions, and is validated in CI (sockets exist on the
hull, regions do not overlap unless intended).

```toml
# knowledge/hulls/vauxhall-light-cruiser.toml
hull = "Stock/Vauxhall Light Cruiser"

[[region]]
name = "nose-stack"
display = "Nose stack"
sockets = ["<socket-key>", "..."]

[[region]]
name = "center-stack"
display = "Central body"
sockets = ["..."]
```

**Claims** ("the central body eats most incoming damage; keep magazines
out") are normal entries with `kind = "anatomy"`, scoped to the hull,
referencing a region as `<hull-file>/<region>` so validation can resolve
it. They carry author, source, status, and votes like every other entry.
The Vauxhall advice is an anatomy entry plus fb-004's `in_region` trigger;
a drydock editor renders the claims as per-socket tooltips using the
geometry.

Open verification item (blocks this layer only): confirm socket `Key`
values are stable per hull across game versions before keying regions to
them. The fleet XML alone cannot prove this; the decompile or a
DevAssistant probe can. If keys are unstable, regions key on socket
names/indices from the catalog dump instead.

### 5. Fleet archetypes: `knowledge/catalog/archetypes.toml`

Most fleets are variations on a small set of standard builds, and a lot of
advice is really about the build, not any single ship. A hand-curated
taxonomy gives that advice something to attach to. Illustrative starting
set, ANS: double Axford frontline; BB plus a light escort; double CL with
cappers; double CL with S3 hybrids and a jammer Sprinter; triple CL. OSP:
double Ocello; two or three Liners.

```toml
[[archetype]]
id = "ans-double-axford"
display = "Double Axford frontline"
faction = "ans"
description = "Two Axfords as the line. The standard ANS bowtank frontline."
counters = []                 # archetype ids this build is strong against (one direction only)

[archetype.match]             # optional, best-effort fleet classifier
hulls = { "Stock/Axford Heavy Cruiser" = { min = 2 } }
```

- Entries reference archetypes through `scope.archetypes`. That gives
  search and browse a fleet-level grouping ("show me double-CL advice") and
  gives guide exports a natural page structure.
- **Counter relations are stored one direction only**: `X.counters = [Y]`
  means X beats Y, and the reverse view is derived at export, so the two
  directions can never disagree. The lists carry the rock-paper-scissors
  graph; the how, why, and conditions live in normal entries scoped to the
  archetypes involved. Matchup claims are contested by nature, so they go
  through the same review loop as everything else; a disputed edge is
  removed or its entry explains the conditions.
- The `match` block reuses the trigger philosophy: a small closed
  vocabulary (`min`/`max`/`exact` hull counts to start), evaluated against
  a fleet file. **Classification reports every archetype that matches and
  never picks a winner**: overlapping definitions (double CL vs triple CL)
  are expected, consumers show all matches, and archetype-scoped advice is
  a lookup by matched id, never an automatic judgment.
- Definitions are community judgment, curated like `classes.toml`.
  Community proposal of archetypes from Discord needs a small model
  extension first (`AdviceProposal` only knows advice add/remove today; an
  `entity_type` column and typed payload come with the community-loop
  phase). Until that lands, archetypes are curated via the review sheet
  and PRs; the ballot path opens afterwards, same intake-cheap flow:
  propose in free text, vote that it is a real build worth naming, curator
  formalizes id and match block at promotion.

**Seed material.** Thread `1461715057166651637` ("Brainstorming Fleets And
Their Counters") is exported to
`knowledge/raw/1461715057166651637-2026-08-18.json` (182 messages). It
contains 15+ structured writeups following a consistent template
(archetype / why it's powerful / counters / balance changes) plus matchup
commentary. Candidate seeds from it: frigate blob; beam-DD capfleet;
capture-fleet family (cringe cappers, torpcorv caps, halfblob-CV caps,
Journeyman half-cap, Levy half-cap); light cavalry (torpcorv blob); SWMG
(S3 bomber double Levy); Kitty Petter (S2 bomber single Levy); torpedo
CVLN; Barracuda R2 Moorline; 4tc Spyglass BB; mixed 450mm + rails; rail DD
array; the CL family (3CL, 2CL caps, 2CL with Ocello-killer S3H, 3CL with
Liner killers). Curation notes: joke entries are easy to spot (the
template and reaction patterns separate them), balance commentary is
PTB-vs-main sensitive and should land `patch_sensitive`, and one
contributor (Lobster) explicitly asked to be consulted before their
writeup goes into a bot. Honor that: credit and jump links are already the
norm, and an explicit consent request from an author blocks ingestion of
their content until they agree.

### 6. Community loop v2: cheap intake, structure at promotion

The voting pipeline (2026-07-30 spec) stays as-is for intake: free-text
`!advice add`, 👍/👎 ballots, incorrect pool. Contributors are never required
to provide structure; curators add it. The back half changes:

- Approved `ca-*` entries are explicitly a staging pool: searchable
  immediately (as today), untagged, unstructured.
- **Promotion keeps the public id.** A promoted community entry lands in
  TOML under its existing `ca-NNN` id, permanently. No renumbering, no
  redirect table, no id allocation race: ids are stable for their lifetime
  regardless of which store currently holds the entry. `!advice remove
  ca-NNN` keeps working unchanged.
- **Promotion ordering is safe by construction.** First the entry lands in
  TOML and deploys; then the DB row is marked `promoted`. During any
  overlap the loader dedupes by id and the curated copy wins, so there is
  no window where the advice disappears or double-serves, and a rollback
  of either side leaves one working copy.
- **Tombstones are permanent.** An approved removal writes the DB
  tombstone (as today) and additionally snapshots the removed entry's rule
  text into the proposal row at resolution time, so the incorrect-pool
  audit and the duplicate-proposal guard keep working after the TOML entry
  is later deleted in a curation pass. Tombstone rows are never cleared: a
  tombstone whose target no longer exists in TOML is a no-op, and a
  rollback that redeploys old TOML cannot resurrect removed advice.
- A periodic promotion pass (the existing `curate-advice` skill, extended)
  takes the staged entries plus the curators' sheet verdicts (6c), adds
  kind/tags/scope/triggers, and applies the results to `entries/*.toml`.
  The commit itself is mechanical; the review already happened.
- Power users contribute structured work (anatomy data, triggers) as PRs
  against `knowledge/` directly. Nobody types socket keys into Discord.

### 6a. Structured hints on input

Contributors know the game well and can often say exactly what a tip applies
to. `!advice add` accepts optional trailing hint segments:

```
!advice add Beam ships need at least 2 FPAs | tags: beams, modules | applies: Mk600, Mk610 Beam Turret
```

- Everything after the first `|` is parsed as `key: value` hints (`tags`,
  `applies`, `hulls`, `faction`). The advice text is validated exactly as
  today.
- Hints are matched softly against catalog aliases: recognized values render
  on the ballot as confirmed ("Applies: Mk600 Beam Cannon"), unrecognized
  ones are kept verbatim and labeled as such. A typo never blocks
  submission.
- Hints are stored on the `AdviceProposal` row (one nullable JSON/text
  column) and shown on the ballot so voters can object to wrong scoping. The
  vote approves the advice text; hints are advisory metadata.
- At promotion time the curator starts from the hints instead of a blank
  scope.

**Guided form path (Discord Modal).** A modal (pop-up form with labeled text
fields) feeds the same hint pipeline. Modals can only be opened from an
interaction (slash command or button click), never directly from a prefix
command, so the bridge is a button:

```
!advice add                → embed + [📝 Propose advice] button
!advice add <free text>    → today's flow (power users, pipe hints)
button click               → modal:
    1. The advice          (required, ≤300 chars, same validator)
    2. When does it apply? (optional → situation hint)
    3. Tags                (optional, "comma-separated: beams, modules")
    4. Applies to          (optional, "components/hulls: Mk600, Vauxhall")
submit                     → same dup-check → same ballot as !advice add
```

Both paths produce one proposal shape (text + hints) through one parser and
one ballot. Implementation notes, sharpened by review:

- **One proposal service backs both paths.** The guild-only check, per-user
  cooldown, propose lock, duplicate checks, and open-ballot cap live in the
  service, not in the prefix-command decorators, because decorators do not
  apply to button clicks or modal submissions.
- The modal submission is deferred immediately (interactions must be
  acknowledged within 3 seconds; the dup-check and DB write may exceed
  that), then the ballot posts as a normal channel message.
- The button lives in a persistent view registered once at startup with
  `timeout=None` and fixed `custom_id`s, so it survives restarts.
- Modal fields are text inputs only at our pinned `discord.py>=2.3`, and
  dropdowns would not fit anyway: Discord caps selects at 25 options, the
  tag vocabulary is already 28, and component lists run to hundreds.
  Soft-matched hints are the validation model in both paths.

Why not validated structured input (the original decision point b): no input
surface we have offers catalog autocomplete inside a form, so contributors
would have to type exact catalog IDs. Rejecting typos costs submissions;
accepting them silently rots the canon. Bundling metadata into the ballot
also conflates "is this advice true?" with "is this metadata correct?": a
good tip with a mistyped scope gets voted down, or worse, approved into
canon with wrong scope backed by vote legitimacy. Hints capture the
contributor's knowledge; validation stays at the curation gate where the
catalog and CI already live. If hints see heavy use, slash commands with
catalog autocomplete on the command arguments are the upgrade path. That is
new machinery, so it waits for proven demand.

### 6b. Staleness: patch-notes triage

When a balance patch drops, run a patch-triage pass (a step in the
curate-advice skill, or a small script):

1. **Regenerate the catalog first.** The diff against the previous catalog
   is itself a mechanical change list (new, removed, renamed components).
2. Map every component/hull mention in the patch notes to catalog IDs. The
   alias table makes this mechanical ("FPA", "Mk600", "Grazer" all
   resolve).
3. Find entries whose `scope`, `trigger`, or text reference those IDs, plus
   everything flagged `patch_sensitive`. Global mechanics changes (armor
   model, seeker logic) will not name components; the triage step routes
   those to review by tag as a judgment call.
4. Emit a review checklist (a QUESTIONS.md section and rows in the review
   sheet). Entries confirmed still true get fresh `verified` +
   `verified_version`; invalidated ones get edited or dropped in the same
   promotion pass.

Patch notes name components, and scope links entries to components, so the
cross-reference is a lookup. Re-vote ballots stay in reserve if triage
passes fall behind.

### 6c. Curator review surface: a sheet, not git

Curators review in Discord or a shared sheet, never in git. The seed
exists: `export_knowledge.py` already writes `advice.csv` /
`questions.csv` review sheets with verdict/notes columns. Extend that
shape into the standing review surface: one sheet holding
approved-but-unpromoted `ca-*` entries, open questions, and patch-triage
flags. Curators fill in the verdict and notes columns; the promotion pass
reads the sheet and applies the results to the TOML files.

The staging rows live in the production SQLite DB, which the exporter
cannot see today, so the sheet loop needs one addition: a management
command that exports proposal rows (pk, status, text, hints, updated-at)
to JSON/CSV, run against the production DB per the ops runbook (or a
copied DB file). Apply is row-level and idempotent: a row whose DB status
changed after export is skipped and re-exported next round, so a stale
sheet can never clobber newer state. No new UI, no web app on the VM.
Until the sheet loop lands, Discord ballots carry review on their own. A
richer surface (web view, Drydock-side editor) can come later if the sheet
proves insufficient.

### 7. Consumers

- **`!advice`**: unchanged UX; better search via aliases; badges from
  `status` and `patch_sensitive` (⚠️ contested / 🕒 patch-sensitive) so
  readers see confidence.
- **`!fleetcheck` (new, phase 3)**: user attaches a `.fleet` file; the bot
  parses it (the formation cog already parses fleet XML) and replies with
  triggered entries per ship, matched archetypes, and any unrecognized
  component IDs. This proves the trigger contract before any in-game mod
  exists and is useful on its own. Input handling, hardened per review:
  attachment size cap (~2 MiB; real fleet files are tens of KiB), reject
  any input containing DTD or entity declarations before parsing, parse
  with stdlib ElementTree inside a thread executor so a hostile file
  cannot stall the event loop, cap the number of ships and sockets
  processed, and paginate findings within Discord embed limits.
- **Drydock / in-game mods**: consume `advice.json` v2 (entries + triggers +
  scope), `catalog.json` (including archetypes), and `hulls.json` as export
  artifacts. The three files are generated together and consumed as a set:
  each carries the same bundle block (corpus git revision, `catalog_version`,
  schema version) so a consumer can detect mismatched halves. Drydock is
  first-party (the user is Davaned), so its real rendering needs
  (per-socket tooltips, fleet-wide lint panel) drive the export shape.
  Delivery mechanism (committed files, release assets, or a Drydock build
  input) is decided at Drydock integration; version the schema and never
  break it silently either way, since other mods and the wiki read the
  same files.
- **Wiki/guides**: Markdown export as today, now grouped by kind, scope,
  and archetype (a per-archetype guide page falls out of `scope.archetypes`).

### 8. Repo topology: defer the split

A first-class standalone corpus comes from schema v2 plus versioned export
artifacts, regardless of git topology. Splitting `knowledge/` into its own
repo now costs real friction (prod deploy rsyncs `knowledge/entries/` today,
the schema validator runs in this repo's CI, and the schema is about to
churn) and buys nothing until a second consumer actually pulls the data.

Decision: keep `knowledge/` in this repo through the phases below; split
when Drydock or another external consumer lands. The vendored `advice.json`
is the consumer contract either way, so the split stays cheap later: move
the directory, point the bot at a pinned export, move the validator tests.

## Phasing

Each phase is independently shippable. User-visible phases carry the house
release ritual (`Config.VERSION` + both changelogs) and any deploy-script
changes they need; those are part of the phase, not an afterthought.

1. **Foundation: compatibility only.** Catalog generation (components,
   hulls with faction, aliases overlay, classes) with the regeneration
   procedure documented and owned; alias-fed search; loader/validator
   accept schema v2 fields with safe defaults for legacy entries (no bulk
   verification claims); deploy-script rsync includes for
   `knowledge/catalog/`. No entry content edits. The only behavior change
   is search recall.
2. **Enrichment: judgment, reviewed as such.** Classify the 47 entries
   (kind, scope, status, patch_sensitive), resolving QUESTIONS.md items
   where possible; seed the archetype taxonomy and counter edges from the
   exported counters thread; build the trigger capability matrix. Reviewed
   through the sheet, entry by entry; explicitly not a mechanical
   spot-check.
3. **Triggers + proof.** Predicate evaluator with conformance fixtures;
   triggers transcribed where the matrix allows; archetype classification;
   `advice.json` v2 with the bundle block; hardened `!fleetcheck`.
4. **Community loop v2.** Migrations: `promoted` status, hints column,
   removal-text snapshot, `entity_type` for archetype ballots. Hint
   parsing, the modal form + button bridge behind one proposal service
   (6a), proposals-export management command + sheet loop (6c), promotion
   pass in the curate-advice skill with id-stable promotion and permanent
   tombstones (6), patch-triage workflow (6b), archetype ballots.
5. **Anatomy + split.** Hull region geometry (after the socket-key
   stability check), anatomy claim entries, `in_region` triggers,
   `hulls.json` export; split the repo when an external consumer lands.

## Decision points, resolved 2026-08-18

a. **Repo split**: deferred until an external consumer is real (8).
b. **Contribution surface**: free-text intake + optional structured hints +
   modal form (6a); validated forms rejected; slash-command autocomplete
   held as the upgrade path if hints see heavy use.
c. **`!fleetcheck`**: confirmed as the initial consumer of the trigger
   layer.
d. **Staleness**: patch-notes triage (6b), human-led; re-vote ballots in
   reserve.
e. **Curator review surface**: Discord ballots plus a shared review sheet;
   git stores canon but nobody reviews there (6c).
f. **Fleet archetypes**: added as a catalog taxonomy with optional
   best-effort fleet classification and one-directional counter relations
   (5); community balloting for archetypes follows the `entity_type` model
   extension; seeded from the "Brainstorming Fleets And Their Counters"
   thread (raw dump committed).

## Out of scope (deliberately)

- Embeddings/semantic search, runtime LLM calls (VM constraints).
- Auto-scraping Discord; reaction-based capture.
- Editing canonical entries from Discord; git remains the editing surface.
- Balance simulation (testloop/missile-test evidence feeding entries is a
  separate pipeline).

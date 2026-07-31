# Community Advice Voting — Design

**Date:** 2026-07-30
**Status:** Implemented (v2.7.0)
**Extends:** `2026-07-13-community-knowledge-base-design.md` (supersedes its
"editing entries from Discord is out of scope" decision)

## Problem

The community likes `!advice`, but the knowledge pool could only change via
the git curation pipeline. Players need to:

1. **Add** new advice directly from Discord.
2. **Correct** the pool when an entry turns out to be wrong.
3. **Audit** everything that's in (and out of) the pool.

Moderation is by community vote, not by admins.

## Constraints

- The curated TOML corpus is baked into the Docker image — the bot cannot
  edit it at runtime, and any runtime state must survive a redeploy. So
  community changes live in the DB (SQLite volume), while git remains the
  editing surface for the curated corpus.
- Same RAM/dependency limits as ever: no new dependencies. Reaction voting
  uses the gateway events already included in default intents.
- Tests stay pure-logic and DB-free.

## Behaviour

- `!advice add <tip>` — posts a ballot embed, bot seeds 👍/👎.
  - **≥ `ADVICE_VOTE_THRESHOLD` (default 5) 👍 and strictly more 👍 than 👎**
    → added to the knowledge pool as entry `ca-<pk>`.
  - **≥ threshold 👎 and strictly more 👎 than 👍** → recorded in the
    *incorrect pool* (and the same text can't be re-proposed verbatim).
  - Ties stay open. Votes are tallied **per user** from the reactions'
    voter lists: the bot's seeds don't count, and one person reacting with
    both emoji cancels out (counts for neither side).
- `!advice remove <id>` — ballot to retract any active entry (curated or
  community). Approval tombstones it out of search and records it in the
  incorrect pool; rejection keeps it. Curated entries stay in git — the
  tombstone is the approved remove-row.
- `!advice list [category|community|incorrect|all] [page]` — full audit
  with entry ids (aliased `!advice audit`); bare `!advice list` shows a
  summary. `!advice pending` links every open ballot.
- Duplicate guards on `add`: exact-text match against active corpus,
  open ballots, and the incorrect pool. `remove` guards against a second
  open ballot for the same target.
- Anti-spam: `add`/`remove` are guild-only with a 2/60s per-user cooldown.

## Mechanics

- **Model:** `AdviceProposal` (migration 0010). `kind` add/remove; `status`
  pending → approved/rejected (+ `removed` for approved adds voted out
  later, `expired` for deleted ballot messages). Approved add-rows ARE the
  community entries; no separate entries table.
- **Resolution:** `on_raw_reaction_add` (works on uncached messages) →
  fetch ballot + per-reaction voter lists → `knowledge.tally_voters` →
  `knowledge.resolve_votes` → atomic claim (`UPDATE ... WHERE
  status='pending'` + asyncio lock) → edit the ballot embed into the
  outcome, update in-memory state. Proposal creation is serialized behind
  its own lock (dup-check → create is race-free) and immediately re-tallies
  once, so reactions landing before the ballot registered aren't lost.
- **Restart safety:** pending ballots reload in `cog_load`; a one-shot
  `on_ready` re-tally catches votes cast while the bot was offline. A
  deleted ballot message voids the proposal (`expired`) — enforced live by
  `on_raw_message_delete`/`on_raw_bulk_message_delete` and at boot by the
  sweep. Open ballots are capped at 25 (`MAX_OPEN_BALLOTS`) so pending
  state can't grow without bound.
- **Search:** `knowledge.active_entries` merges curated + community minus
  removed ids. Community entries have no tags/situation/reason; their
  `source_url` is the ballot jump link (provenance + who voted).
- All vote logic is pure (`knowledge.resolve_votes` / `count_votes` /
  `community_entry` / `normalize_entry_id`), covered DB-free by
  `nebulous_bot/tests/test_advice_votes.py`.

## Notes / future

- The knowledge pool is global across guilds (as before); ballots happen in
  whichever guild proposes them. Fine while the bot serves one community.
- Periodically, approved `ca-*` entries can be promoted into the curated
  TOML corpus by the existing curation pipeline (add situation/reason/tags),
  then the DB rows retired — not automated yet.
- `scripts/export_knowledge.py` still exports only the curated TOML corpus;
  fold community entries in if the shipbuilding mod wants them.

# Ticket: `!advice improve` (community corrections to existing advice)

**Date:** 2026-08-18
**Status:** Ticket only. Follow-up work, not scheduled. Requested by
Davaned during phase 1 of the KB v2 build.
**Home:** slots into phase 4 (community loop v2) of
`docs/superpowers/specs/2026-08-18-knowledge-base-v2-structured-advice.md`,
alongside structured hints, because both are cheap intake that curators
formalize at promotion.

## Problem

Feedback on existing advice currently has only two channels: propose a
brand-new entry (which breeds near-duplicates) or vote the entry out
(which throws away advice that is right but incomplete). There is no way
to say "fb-016 is correct, but railgun ships are an exception" without
minting a new id.

## Proposal

```
!advice improve <id> <correction or additional context>
```

A third proposal kind through the exact same ballot pipeline as add and
remove: guild-only, cooldown, dup-check, 5+ thumbs with strict majority.
The ballot shows the target entry's current text next to the proposed
improvement so voters judge the delta, not the entry.

On approval the improvement becomes a community addendum attached to the
entry id: rendered with the entry in `!advice` results (an *Addendum:*
line with author credit), indexed by search, and queued for curation.
The canonical TOML text still changes only in git: the spec explicitly
keeps "editing canonical entries from Discord" out of scope, and this
ticket honors that. At the next promotion pass the curator folds the
addendum into the entry properly (usually the v2 `exceptions` field, a
reason edit, or a `status = "contested"` flip) and retires the addendum
row. For `ca-*` entries the curator can simply amend the row text at
promotion time.

## Implementation notes

- `AdviceProposal` already has `advice_text` plus `target_entry_id`, so
  `kind='improve'` needs no new columns, only a choices migration that
  batches with the migrations phase 4 already plans.
- Reuse the proposal service phase 4 introduces (the checks must live
  behind the modal path too, not in command decorators).
- Approved improvements load in `cog_load` beside approved adds and
  render in the results embed; cap addenda shown per entry (2?) with the
  rest visible via `!advice list`.
- Removal interaction: a tombstoned entry's addenda die with it. An
  addendum on a curated entry survives catalog regeneration by
  construction (it keys on the entry id).

## Open questions

- Verb: `improve`, `amend`, or `note`. `improve` reads best in help text.
- Should an approved improvement bump the entry to `status =
  "contested"` automatically when it contradicts (rather than extends)
  the rule? Probably no: let the curator judge, the ballot only
  establishes community support.
- Cap on open improve ballots per target entry (1 seems right).

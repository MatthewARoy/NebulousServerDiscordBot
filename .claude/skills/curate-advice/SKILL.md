---
name: curate-advice
description: Curate a raw Discord dump (knowledge/raw/*.json) into structured knowledge-base entries (knowledge/entries/*.toml). Use when the user asks to curate, ingest, or extract community advice from an exported thread/channel.
---

# Curating community advice

Turn a raw Discord export into reviewed, structured advice entries. The
canonical format and pipeline are specified in
`docs/superpowers/specs/2026-07-13-community-knowledge-base-design.md`.

## Inputs

- A raw dump: `knowledge/raw/<channel_id>-<date>.json` (produce one first
  with `python scripts/export_thread.py <id>` if needed).
- Existing entries: `knowledge/entries/*.toml`.
- Tag vocabulary: `knowledge/tags.toml`.

## Procedure

1. **Read the whole dump before extracting anything.** Threads are messy:
   tips span multiple messages, later messages correct earlier ones, banter
   interleaves with advice, and replies (`reply_to_id`) often carry the
   context that makes a message meaningful. Reaction counts are a quality
   signal — heavily-reacted messages are usually good advice.
2. **Extract candidate entries** in Situation ⇒ Rule ⇒ Reason form:
   - `rule` (required): one actionable sentence in your own words if the
     source is fragmentary, faithful to the author's meaning.
   - `situation` / `reason`: only when the source actually supplies them —
     never invent context.
   - A tip spread over several messages becomes ONE entry; `source_url` and
     `author` point at the anchor message (the one carrying the rule).
   - Drop: questions, banter, memes, superseded/corrected advice (keep the
     correction), advice about specific patch-day balance numbers unless
     clearly still current.
3. **Dedupe** against every existing entries file. Same rule ⇒ keep the
   better-sourced entry (clearer wording, more reactions, more authoritative
   author); never keep both.
4. **Tag from `knowledge/tags.toml` only.** If an entry genuinely needs a
   new tag, add it to `tags.toml` with a one-line description in the same
   commit — never invent a tag silently, and prefer reusing an existing one.
5. **Ids**: `<prefix>-<3-digit seq>` where the prefix comes from the
   category filename (`fleet-building` → `fb`, `team-comp` → `tc`,
   `gameplay` → `gp`). Continue from the highest existing sequence; never
   reuse or renumber an id — the shipbuilding mod references them.
6. **Log uncertainty instead of guessing.** Contradictory advice, unclear
   meaning, possibly-outdated references, or judgment calls you were forced
   to make go in `knowledge/QUESTIONS.md` as checklist items with the source
   jump link. A human resolves them later; entries you are unsure about
   still ship, flagged there.
7. **Bulk processing may be delegated** (e.g. Haiku subagents chunking a
   long dump into candidate entries), but you — the curating session — own
   final wording, dedupe, tags, and ids. Never commit subagent output
   unreviewed.
8. **Validate**: run
   `.venv/bin/python -m pytest nebulous_bot/tests/test_knowledge_entries.py -q`
   (POSIX; `.venv/Scripts/python` on Windows) and fix failures.
9. **Hand off for review**: the git diff of `knowledge/` is the review
   surface. Summarize what was added, dropped, and questioned. Do not
   commit without the user seeing the summary unless they pre-authorized it.
10. After entries land, refresh derived artifacts when asked:
    `python scripts/export_knowledge.py`.

## Entry format

```toml
[[entry]]
id = "fb-001"
situation = "Fighting OSP missile spam"        # optional
rule = "Bring at least one dedicated PD escort per capital ship"
reason = "PD saturation scales worse than missile volume"  # optional
tags = ["missiles", "point-defense"]
author = "SomeVet"
source_url = "https://discord.com/channels/409638848302153728/…/…"
curated = 2026-07-13
```

Category = filename (`knowledge/entries/fleet-building.toml`). Create a new
category file only when advice clearly doesn't fit an existing one.

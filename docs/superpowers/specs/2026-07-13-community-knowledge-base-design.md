# Community Knowledge Base — Design

**Date:** 2026-07-13
**Status:** Approved (brainstormed and approved in-session; autonomous execution authorized)

## Problem

The main Nebulous: Fleet Command Discord holds a lot of high-quality,
unstructured community advice — fleet building, team composition, gameplay.
Example: thread `1508914822597709855` in guild `409638848302153728` contains
fleet-building tips loosely following a "Situation ⇒ Rule ⇒ Reason" pattern
across many messy free-form messages.

We want that knowledge to be:

1. **Searchable from Discord** via a bot command, so new players can query it.
2. **Exportable** as structured data for wiki pages, guides, and — immediately —
   an in-game shipbuilding mod.
3. **Repeatably extractable**: future threads/channels (e.g. `#shipyard`) can be
   ingested with the same pipeline without new engineering.

## Constraints

- Production VM has ~503 MiB usable RAM. **No new heavy dependencies, no
  embeddings/vector search.** Python 3.11 stdlib `tomllib` is the only new
  format machinery.
- The bot is stable; changes must be small and independently verifiable.
- Tests are pure-logic and DB-free.
- Curation quality matters more than automation: a human reviews every entry
  before it lands (git diff review).

## Decisions (made during brainstorming)

| Decision | Choice |
|---|---|
| Ingestion model | One-shot export + LLM curation (repeatable per thread/channel) |
| Canonical KB home | `knowledge/entries/` directory in this repo |
| Raw export mechanism | Local standalone script hitting Discord REST with the bot token (no gateway, nothing on prod VM) |
| Entry format | TOML (`tomllib` is stdlib in 3.11; human-editable; git-reviewable) |
| Bot search | In-memory keyword/tag scoring — corpus is hundreds of entries at most |
| Mod/wiki output | Generated exports (JSON + Markdown), never hand-edited |
| Curation compute | Claude session following a documented skill; Haiku subagents allowed for bulk message processing |

## Architecture

```
Discord thread/channel
        │  scripts/export_thread.py <id>          (local, REST, bot token)
        ▼
knowledge/raw/<id>-<date>.json                    (committed: provenance)
        │  .claude/skills/curate-advice/          (LLM curation, human diff review)
        ▼
knowledge/entries/<category>.toml                 (committed: CANONICAL)
        │                          │
        │ cogs/advice.py           │ scripts/export_knowledge.py
        ▼                          ▼
!advice <query> in Discord    knowledge/exports/advice.json      (mod)
                              knowledge/exports/<category>.md    (wiki/guides)
```

## Components

### 1. Knowledge directory

```
knowledge/
  raw/          # committed raw dumps — provenance for curation review
  entries/      # canonical KB: one TOML file per category
  exports/      # gitignored generated artifacts
  tags.toml     # controlled tag vocabulary (outside entries/, see below)
  QUESTIONS.md  # open clarification questions from curation, for human review
```

Entry schema (`category` is the filename stem, not repeated per entry):

```toml
[[entry]]
id = "fb-001"            # stable slug: <category-prefix>-<seq>; never reused
situation = "..."        # optional — not all advice fits S/R/R
rule = "..."             # required: the actionable statement
reason = "..."           # optional
tags = ["missiles", "point-defense"]   # from the controlled vocabulary
author = "DiscordDisplayName"
source_url = "https://discord.com/channels/<guild>/<channel>/<message>"
curated = 2026-07-13     # TOML date
```

Validation rules (enforced by a pytest test, so CI guards every curation
commit): ids unique across all files, `rule` non-empty, `source_url` a
`discord.com/channels/` URL, tags drawn from the vocabulary file, valid date.
The controlled tag vocabulary lives at `knowledge/tags.toml` (list of
tag + one-line meaning) so both the curation skill and the validator share it.
It sits outside `entries/` so the cog's `entries/*.toml` glob never mistakes
it for a category file.

### 2. `scripts/export_thread.py`

Standalone (no Django import — avoids the manage.py env-var dance).
`python scripts/export_thread.py <channel_or_thread_id> [--out path]`.

- Loads `DISCORD_TOKEN` from `.env` via python-dotenv.
- Pages `GET /channels/{id}/messages?limit=100&before=<cursor>` with aiohttp,
  honouring `X-RateLimit-Remaining`/`Retry-After` (sleep-and-retry on 429).
- Emits `knowledge/raw/<id>-<YYYY-MM-DD>.json`: channel metadata + messages
  (id, author id/display name, ISO timestamp, content, reply reference,
  jump URL, reaction summary), oldest-first.
- Reactions are captured because they are a curation quality signal
  (heavily-reacted advice is likely good).
- Works for threads and normal channels alike (same endpoint) — this is the
  "flexible extraction going forward" hook; `#shipyard` needs no new code.

### 3. Curation skill — `.claude/skills/curate-advice/SKILL.md`

The repeatable procedure a Claude session follows:

1. Read the raw dump. Expect mess: fragments, banter, corrections in later
   messages, multi-message tips, contradictions.
2. Extract candidate entries into Situation/Rule/Reason. A tip spread over
   several messages becomes one entry sourced to its anchor message. Banter,
   questions, and superseded advice are dropped.
3. Dedupe against existing `knowledge/entries/*.toml` (same rule ⇒ keep the
   better-sourced one).
4. Tag from the controlled vocabulary; propose new tags explicitly rather
   than inventing silently.
5. Anything ambiguous (contradictory advice, unclear meaning, possibly
   outdated balance references) goes to `knowledge/QUESTIONS.md` with a link
   to the source message — curation never guesses silently.
6. Bulk processing may be delegated to Haiku subagents; the curating session
   remains responsible for final entry quality.
7. Output: appended TOML entries + updated QUESTIONS.md; validate by running
   the schema test; human reviews the git diff before commit.

### 4. Bot command — `cogs/advice.py`

`AdviceCog`, registered in runbot.py alongside the other cogs.

- Loads every `knowledge/entries/*.toml` at boot (eager, consistent with
  house style; RAM cost is a few hundred KiB). A file that fails to parse is
  logged and skipped — the bot must boot even with a bad KB file.
- `!advice <query>`: lowercase-tokenize the query; score each entry
  (exact tag match = 3, word hit in `rule` = 2, word hit in
  `situation`/`reason` = 1); return the top 3 in one embed — rule in bold,
  situation/reason as body, author credit + jump link. No hits ⇒ reply with
  available tags.
- `!advice` (bare) or `!advice tags`: list categories and tag vocabulary.
- Replies are plain static messages (not tracked/self-refreshing).
- No DB, no migrations, no new dependencies.

### 5. `scripts/export_knowledge.py`

Standalone, Django-free. Reads `knowledge/entries/`, writes
`knowledge/exports/`:

- `--format json`: single `advice.json` — `{"generated": ..., "entries":
  [{id, category, situation, rule, reason, tags, author, source_url}]}`.
  Stable shape; the shipbuilding mod bundles this file at build time.
- `--format markdown`: one page per category, entries grouped by primary
  tag, with attribution and source links — wiki/guide-ready.
- No flag: both.

## Error handling

- Export script: exits non-zero with a clear message on bad token / no access
  / unknown channel; partial pages are not written (atomic write via temp
  file + rename).
- Cog: missing/empty `knowledge/entries/` ⇒ `!advice` replies "no advice
  loaded yet" rather than erroring; parse failures logged at startup.
- Validator test fails CI on any malformed entry, so prod never loads bad data.

## Testing

- `nebulous_bot/tests/test_advice_search.py`: pure-logic scoring tests
  (tag beats keyword, multi-word queries, no-hit behaviour) constructing the
  cog via `__new__` per house pattern.
- `nebulous_bot/tests/test_knowledge_entries.py`: schema validation over the
  real `knowledge/entries/` files (ids unique, required fields, tag
  vocabulary membership, URL shape).
- Scripts: pagination/rate-limit handling kept in small pure functions,
  tested without network where practical.

## Deployment notes

- `deployment/oracle/deploy-to-oracle.sh` rsync includes must pick up
  `knowledge/entries/` (and `tags.toml`) or prod loads an empty KB. Raw dumps
  and exports do NOT need to ship.
- User-facing feature ⇒ `Config.VERSION` bump + both changelogs
  (`Config.CHANGELOG` and `CHANGELOG.md`) per house rules.

## Out of scope (deliberately)

- Embeddings / semantic search (RAM; corpus too small to need it).
- Runtime LLM calls from the bot (cost, keys, latency on a starved VM).
- Continuous auto-scraping; reaction-based capture (may revisit after the
  manual pipeline proves out).
- Editing entries from Discord — git is the editing surface.

## Success criteria

1. Thread `1508914822597709855` is exported, curated into TOML entries, and
   `!advice` answers queries against it with source attribution.
2. `advice.json` exists and is consumable by the shipbuilding mod.
3. A future `#shipyard` extraction requires only: run export script → run
   curation skill → review diff → commit.

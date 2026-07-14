"""Loading and searching the community knowledge base.

The canonical data is `knowledge/entries/*.toml` at the repo root — curated
community advice entries (see docs/superpowers/specs/
2026-07-13-community-knowledge-base-design.md). This module is pure stdlib
(no Django, no discord.py) so the advice cog, the export script, and the
tests all share one loader and one search implementation.
"""
import logging
import re
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / 'knowledge'
ENTRIES_DIR = KNOWLEDGE_DIR / 'entries'
TAGS_FILE = KNOWLEDGE_DIR / 'tags.toml'

# Search scoring weights: an exact tag match is the strongest signal,
# a word in the rule text is next, words in situation/reason weakest.
TAG_WEIGHT = 3
RULE_WEIGHT = 2
BODY_WEIGHT = 1

_WORD_RE = re.compile(r'[a-z0-9]+')


def tokenize(text):
    """Lowercase word tokens; hyphenated terms yield their parts too."""
    return _WORD_RE.findall(text.lower())


def load_entries(entries_dir=None):
    """Load all category files into a list of entry dicts.

    Each entry gains a `category` key from its filename stem. A file that
    fails to parse is logged and skipped so a bad curation commit can never
    stop the bot from booting.
    """
    entries_dir = Path(entries_dir) if entries_dir else ENTRIES_DIR
    entries = []
    if not entries_dir.is_dir():
        return entries
    for path in sorted(entries_dir.glob('*.toml')):
        try:
            with open(path, 'rb') as f:
                data = tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError) as e:
            logger.error("Skipping unreadable knowledge file %s: %s", path, e)
            continue
        for entry in data.get('entry', []):
            entry['category'] = path.stem
            entries.append(entry)
    return entries


def load_tags(tags_file=None):
    """Return the controlled tag vocabulary as {tag: description}."""
    tags_file = Path(tags_file) if tags_file else TAGS_FILE
    try:
        with open(tags_file, 'rb') as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        logger.error("Could not read tag vocabulary %s: %s", tags_file, e)
        return {}
    return {t['name']: t.get('description', '') for t in data.get('tag', [])}


def score_entry(query_tokens, entry):
    """Score one entry against pre-tokenized query words."""
    score = 0
    tag_words = set()
    for tag in entry.get('tags', []):
        tag_words.update(tokenize(tag))
    rule_words = set(tokenize(entry.get('rule', '')))
    body_words = set(tokenize(entry.get('situation', ''))) | set(tokenize(entry.get('reason', '')))
    for token in query_tokens:
        if token in tag_words:
            score += TAG_WEIGHT
        if token in rule_words:
            score += RULE_WEIGHT
        elif token in body_words:
            score += BODY_WEIGHT
    return score


def search(entries, query, limit=3):
    """Return the top-scoring entries for a free-text query, best first."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    scored = []
    for entry in entries:
        s = score_entry(query_tokens, entry)
        if s > 0:
            scored.append((s, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get('id', '')))
    return [entry for _score, entry in scored[:limit]]

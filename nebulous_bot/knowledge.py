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
QUESTIONS_FILE = KNOWLEDGE_DIR / 'QUESTIONS.md'

# Search scoring weights: an exact tag match is the strongest signal,
# a word in the rule text is next, words in situation/reason weakest.
TAG_WEIGHT = 3
RULE_WEIGHT = 2
BODY_WEIGHT = 1

# Community-vote plumbing shared by the advice cog and the pure-logic tests.
COMMUNITY_CATEGORY = 'community'
COMMUNITY_ID_PREFIX = 'ca'
UP_EMOJI = '\N{THUMBS UP SIGN}'
DOWN_EMOJI = '\N{THUMBS DOWN SIGN}'

_WORD_RE = re.compile(r'[a-z0-9]+')
_ENTRY_ID_RE = re.compile(r'^([a-z]{2,3})-0*(\d+)$')


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


def load_questions(questions_file=None):
    """Parse the QUESTIONS.md checklist into structured items.

    Returns dicts with `title` (the bold lead-in), `text` (the whole item
    as plain text), `entry_ids` (every entry id mentioned), `links`
    (Discord URLs), and `resolved` (checkbox state). QUESTIONS.md stays
    the single source of truth; exports derive their flags from here.
    """
    path = Path(questions_file) if questions_file else QUESTIONS_FILE
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as e:
        logger.error("Could not read questions file %s: %s", path, e)
        return []
    items = []
    boxes = list(re.finditer(r'^- \[(.)\] ', text, re.MULTILINE))
    for i, box in enumerate(boxes):
        end = boxes[i + 1].start() if i + 1 < len(boxes) else len(text)
        body = text[box.end():end].split('\n#')[0].strip()
        title_match = re.match(r'\*\*(.+?)\*\*', body, re.DOTALL)
        plain = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', body)
        plain = re.sub(r'\s+', ' ', plain.replace('**', '').replace('`', '')).strip()
        items.append({
            'title': ' '.join(title_match.group(1).split()) if title_match else '',
            'text': plain,
            'entry_ids': sorted(set(re.findall(r'\b[a-z]{2,3}-\d{3}\b', body))),
            'links': re.findall(r'\((https://discord\.com/[^)]+)\)', body),
            'resolved': box.group(1).lower() == 'x',
        })
    return items


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


def count_votes(reactions):
    """Tally (up, down) from reaction summaries.

    `reactions` is an iterable of `(emoji, count, includes_bot)` tuples —
    the bot seeds one 👍 and one 👎 on every ballot so voters can one-click,
    and those seeds must not count.
    """
    up = down = 0
    for emoji, count, includes_bot in reactions:
        if emoji == UP_EMOJI:
            up = max(0, count - (1 if includes_bot else 0))
        elif emoji == DOWN_EMOJI:
            down = max(0, count - (1 if includes_bot else 0))
    return up, down


def resolve_votes(up, down, threshold=5):
    """Decide a pending ballot: 'approved', 'rejected', or None (still open).

    Either verdict needs `threshold` votes AND a strict majority, so a tie
    stays open no matter how large it grows.
    """
    if down >= threshold and down > up:
        return 'rejected'
    if up >= threshold and up > down:
        return 'approved'
    return None


def community_entry_id(pk):
    """Stable public id for a community-approved entry ("ca-007")."""
    return f'{COMMUNITY_ID_PREFIX}-{pk:03d}'


def normalize_entry_id(raw):
    """Canonicalize a user-typed entry id ("FB-3" -> "fb-003"), or None."""
    m = _ENTRY_ID_RE.match(raw.strip().lower())
    if not m:
        return None
    return f'{m.group(1)}-{int(m.group(2)):03d}'


def community_entry(pk, rule, author, source_url=''):
    """Shape a community-approved submission like a curated TOML entry."""
    return {
        'id': community_entry_id(pk),
        'rule': rule,
        'author': author,
        'source_url': source_url,
        'tags': [],
        'category': COMMUNITY_CATEGORY,
    }


def active_entries(curated, community, removed_ids):
    """The searchable corpus: curated + community, minus voted-out ids."""
    entries = [e for e in curated if e.get('id') not in removed_ids]
    entries.extend(e for e in community if e.get('id') not in removed_ids)
    return entries

"""Schema validation over the real knowledge base files.

This is the CI gate for curation commits: every entry in
knowledge/entries/*.toml must be well-formed, uniquely identified, and
tagged from the controlled vocabulary in knowledge/tags.toml.
"""
import datetime

from nebulous_bot import knowledge


def test_entries_are_valid():
    entries = knowledge.load_entries()
    vocabulary = set(knowledge.load_tags())

    seen_ids = set()
    for entry in entries:
        ident = entry.get('id')
        assert ident, f"Entry without id in {entry['category']}: {entry!r}"
        assert ident not in seen_ids, f"Duplicate entry id {ident}"
        seen_ids.add(ident)

        assert entry.get('rule', '').strip(), f"{ident}: rule is required"

        url = entry.get('source_url', '')
        assert url.startswith('https://discord.com/channels/'), \
            f"{ident}: source_url must be a Discord jump link, got {url!r}"

        assert isinstance(entry.get('curated'), datetime.date), \
            f"{ident}: curated must be a TOML date"

        tags = entry.get('tags', [])
        assert tags, f"{ident}: at least one tag required"
        unknown = set(tags) - vocabulary
        assert not unknown, \
            f"{ident}: tags {sorted(unknown)} not in knowledge/tags.toml"


def test_tag_vocabulary_is_wellformed():
    tags = knowledge.load_tags()
    if not knowledge.ENTRIES_DIR.is_dir():
        return  # no KB checked out at all — nothing to enforce
    assert tags, "knowledge/tags.toml missing or empty"
    for name in tags:
        assert name == name.lower(), f"tag {name!r} must be lowercase"
        assert ' ' not in name, f"tag {name!r} must use hyphens, not spaces"

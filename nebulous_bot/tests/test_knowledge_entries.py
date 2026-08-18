"""Schema validation over the real knowledge base files.

This is the CI gate for curation commits: every entry in
knowledge/entries/*.toml must be well-formed, uniquely identified, and
tagged from the controlled vocabulary in knowledge/tags.toml. Schema v2
fields (kind/status/patch_sensitive/verified/exceptions/scope) are
optional but validated when present, with scope ids resolved against
knowledge/catalog/. The catalog overlays (aliases, classes) are validated
against the generated catalog here too.
"""
import datetime

from nebulous_bot import knowledge


def _known_component_ids(catalog):
    return set(catalog['components']) | set(catalog['munitions'])


def test_entries_are_valid():
    entries = knowledge.load_entries()
    vocabulary = set(knowledge.load_tags())
    catalog = knowledge.load_catalog()
    known_factions = {h['faction'] for h in catalog['hulls'].values()}
    known_components = _known_component_ids(catalog)
    known_archetypes = set()  # archetypes.toml lands in a later phase

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

        # --- schema v2 (loader defaults kind/status/patch_sensitive) ---
        assert entry['kind'] in knowledge.ENTRY_KINDS, \
            f"{ident}: kind {entry['kind']!r} not in {knowledge.ENTRY_KINDS}"
        assert entry['status'] in knowledge.ENTRY_STATUSES, \
            f"{ident}: status {entry['status']!r} not in {knowledge.ENTRY_STATUSES}"
        assert isinstance(entry['patch_sensitive'], bool), \
            f"{ident}: patch_sensitive must be a boolean"
        if 'verified' in entry:
            assert isinstance(entry['verified'], datetime.date), \
                f"{ident}: verified must be a TOML date"
            assert isinstance(entry.get('verified_version'), str) and entry['verified_version'], \
                f"{ident}: verified needs a non-empty verified_version"
        else:
            assert 'verified_version' not in entry, \
                f"{ident}: verified_version without a verified date"
        if 'exceptions' in entry:
            assert isinstance(entry['exceptions'], str), \
                f"{ident}: exceptions must be a string"

        scope = entry.get('scope', {})
        assert isinstance(scope, dict), f"{ident}: scope must be a table"
        unknown_keys = set(scope) - set(knowledge.SCOPE_KEYS)
        assert not unknown_keys, \
            f"{ident}: unknown scope keys {sorted(unknown_keys)}"
        for key, values in scope.items():
            assert isinstance(values, list) and all(isinstance(v, str) for v in values), \
                f"{ident}: scope.{key} must be a list of strings"
        bad = set(scope.get('factions', [])) - known_factions
        assert not bad, f"{ident}: scope.factions {sorted(bad)} not in the catalog"
        bad = set(scope.get('hulls', [])) - set(catalog['hulls'])
        assert not bad, f"{ident}: scope.hulls {sorted(bad)} not in the catalog"
        for value in scope.get('components', []):
            if value.startswith('class:'):
                assert value[len('class:'):] in catalog['classes'], \
                    f"{ident}: scope class {value!r} not in classes.toml"
            else:
                assert value in known_components, \
                    f"{ident}: scope component {value!r} not in the catalog"
        bad = set(scope.get('archetypes', [])) - known_archetypes
        assert not bad, f"{ident}: scope.archetypes {sorted(bad)} not defined"


def test_tag_vocabulary_is_wellformed():
    tags = knowledge.load_tags()
    if not knowledge.ENTRIES_DIR.is_dir():
        return  # no KB checked out at all — nothing to enforce
    assert tags, "knowledge/tags.toml missing or empty"
    for name in tags:
        assert name == name.lower(), f"tag {name!r} must be lowercase"
        assert ' ' not in name, f"tag {name!r} must use hyphens, not spaces"


def test_catalog_is_wellformed():
    """The generated catalog files parse and carry their provenance."""
    catalog = knowledge.load_catalog()
    assert catalog['version'], "catalog files missing their catalog_version header"
    assert catalog['components'], "components.toml has no components"
    assert catalog['munitions'], "components.toml has no munitions"
    assert catalog['hulls'], "hulls.toml has no hulls"
    for hull_id, hull in catalog['hulls'].items():
        assert hull['faction'] in ('ans', 'osp', 'civilian'), \
            f"{hull_id}: unexpected faction {hull['faction']!r}"
        assert hull['display'], f"{hull_id}: empty display name"
        assert hull['class'], f"{hull_id}: empty class name"


def test_alias_search_finds_shorthand():
    """End to end over the real files: the motivating case for the catalog
    is that searching "FPA" finds fb-001, which spells the name out."""
    entries = knowledge.load_entries()
    expansions = knowledge.alias_expansions(knowledge.load_catalog())
    results = knowledge.search(entries, 'FPA', expansions=expansions)
    assert 'fb-001' in [e['id'] for e in results]


def test_catalog_overlays_resolve():
    """Alias targets and class members must exist in the generated catalog,
    and names must be unique — the CI contract that lets a regeneration
    diff be trusted. Uniqueness is checked on the raw files: load_catalog
    folds names into dicts, where a duplicate would silently overwrite.
    """
    import tomllib

    catalog = knowledge.load_catalog()
    known = _known_component_ids(catalog) | set(catalog['hulls'])

    with open(knowledge.CATALOG_DIR / 'aliases.toml', 'rb') as f:
        raw_aliases = tomllib.load(f)
    seen_alias_names = set()
    for row in raw_aliases.get('alias', []):
        assert row.get('id') in known, \
            f"alias target {row.get('id')!r} not in the catalog"
        for name in row.get('names', []):
            assert name.lower() not in seen_alias_names, \
                f"duplicate alias name {name!r}"
            seen_alias_names.add(name.lower())

    with open(knowledge.CATALOG_DIR / 'classes.toml', 'rb') as f:
        raw_classes = tomllib.load(f)
    seen_class_names = set()
    for row in raw_classes.get('class', []):
        class_name = row.get('name', '')
        assert class_name == class_name.lower() and ' ' not in class_name and class_name, \
            f"class {class_name!r} must be lowercase-hyphenated"
        assert class_name not in seen_class_names, f"duplicate class {class_name!r}"
        seen_class_names.add(class_name)
        members = row.get('members', [])
        assert members, f"class {class_name!r} has no members"
        for member in members:
            assert member in _known_component_ids(catalog), \
                f"class {class_name!r} member {member!r} not in components.toml"

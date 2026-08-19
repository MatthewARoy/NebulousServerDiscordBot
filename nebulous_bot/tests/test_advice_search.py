"""Pure-logic tests for knowledge-base search scoring."""
from nebulous_bot import knowledge


def _entry(**kwargs):
    base = {
        'id': 'x-000',
        'rule': '',
        'tags': [],
        'category': 'test',
    }
    base.update(kwargs)
    return base


def test_tokenize_lowercases_and_splits_hyphens():
    assert knowledge.tokenize('Point-Defense PD') == ['point', 'defense', 'pd']


def test_tag_match_outscores_rule_match():
    tagged = _entry(id='a', tags=['missiles'], rule='bring guns')
    ruled = _entry(id='b', rule='use missiles wisely')
    q = knowledge.tokenize('missiles')
    assert knowledge.score_entry(q, tagged) > knowledge.score_entry(q, ruled)


def test_rule_match_outscores_body_match():
    ruled = _entry(id='a', rule='stagger your torpedoes')
    body = _entry(id='b', rule='other', reason='torpedoes get intercepted')
    q = knowledge.tokenize('torpedoes')
    assert knowledge.score_entry(q, ruled) > knowledge.score_entry(q, body)


def test_hyphenated_tag_matches_split_query_words():
    entry = _entry(tags=['point-defense'])
    assert knowledge.score_entry(knowledge.tokenize('point defense'), entry) > 0


def test_multi_word_query_accumulates():
    entry = _entry(rule='keep your radar on', situation='hunting corvettes')
    one = knowledge.score_entry(knowledge.tokenize('radar'), entry)
    two = knowledge.score_entry(knowledge.tokenize('radar corvettes'), entry)
    assert two > one


def test_search_orders_by_score_and_limits():
    entries = [
        _entry(id='weak', reason='missiles mentioned in passing'),
        _entry(id='strong', tags=['missiles'], rule='missiles need spotting'),
        _entry(id='medium', rule='dodge missiles'),
        _entry(id='none', rule='unrelated'),
    ]
    results = knowledge.search(entries, 'missiles', limit=2)
    assert [e['id'] for e in results] == ['strong', 'medium']


def test_search_empty_query_returns_nothing():
    entries = [_entry(rule='anything')]
    assert knowledge.search(entries, '   ') == []


def test_search_no_hits_returns_empty():
    entries = [_entry(rule='beam frigates')]
    assert knowledge.search(entries, 'xyzzy') == []


def test_ties_break_deterministically_by_id():
    entries = [
        _entry(id='b', rule='use chaff'),
        _entry(id='a', rule='use chaff'),
    ]
    results = knowledge.search(entries, 'chaff')
    assert [e['id'] for e in results] == ['a', 'b']


def test_load_entries_missing_dir_is_empty(tmp_path):
    assert knowledge.load_entries(tmp_path / 'nope') == []


def test_load_questions_parses_checklist(tmp_path):
    qfile = tmp_path / 'QUESTIONS.md'
    qfile.write_text(
        '# Open curation questions\n\n'
        'Preamble text.\n\n'
        '## Section\n\n'
        '- [ ] **ARR threshold** — fb-010 says one thing, the\n'
        '  [source](https://discord.com/channels/1/2/3) another. Also fb-011.\n'
        '- [x] **Resolved item** — `code` was fixed.\n',
        encoding='utf-8')
    items = knowledge.load_questions(qfile)
    assert len(items) == 2
    first, second = items
    assert first['title'] == 'ARR threshold'
    assert first['entry_ids'] == ['fb-010', 'fb-011']
    assert first['links'] == ['https://discord.com/channels/1/2/3']
    assert 'source' in first['text'] and '[' not in first['text']
    assert not first['resolved']
    assert second['resolved']
    assert 'code was fixed' in second['text']


def test_load_questions_missing_file_is_empty(tmp_path):
    assert knowledge.load_questions(tmp_path / 'nope.md') == []


def test_real_questions_reference_real_entries():
    ids = {e['id'] for e in knowledge.load_entries()}
    for q in knowledge.load_questions():
        unknown = set(q['entry_ids']) - ids
        assert not unknown, f"QUESTIONS.md references unknown entries: {sorted(unknown)}"


def test_load_entries_skips_bad_file_keeps_good(tmp_path):
    (tmp_path / 'good.toml').write_text(
        '[[entry]]\nid = "g-001"\nrule = "works"\n', encoding='utf-8')
    (tmp_path / 'bad.toml').write_text('not [ valid toml', encoding='utf-8')
    entries = knowledge.load_entries(tmp_path)
    assert [e['id'] for e in entries] == ['g-001']
    assert entries[0]['category'] == 'good'


# --- schema v2 loader defaults ------------------------------------------

def test_load_entries_applies_v2_defaults(tmp_path):
    (tmp_path / 'legacy.toml').write_text(
        '[[entry]]\nid = "l-001"\nrule = "old entry"\n', encoding='utf-8')
    entry = knowledge.load_entries(tmp_path)[0]
    assert entry['kind'] == 'rule'
    assert entry['status'] == 'established'
    assert entry['patch_sensitive'] is False
    # No bulk verification claims: these stay absent on legacy entries.
    for key in ('verified', 'verified_version', 'exceptions', 'scope'):
        assert key not in entry


def test_load_entries_preserves_v2_fields(tmp_path):
    (tmp_path / 'v2.toml').write_text(
        '[[entry]]\n'
        'id = "v-001"\n'
        'kind = "concept"\n'
        'rule = "new entry"\n'
        'status = "contested"\n'
        'patch_sensitive = true\n'
        'verified = 2026-08-18\n'
        'verified_version = "0.6.2.5"\n'
        'exceptions = "unless it is Tuesday"\n'
        '[entry.scope]\n'
        'factions = ["ans"]\n',
        encoding='utf-8')
    entry = knowledge.load_entries(tmp_path)[0]
    assert entry['kind'] == 'concept'
    assert entry['status'] == 'contested'
    assert entry['patch_sensitive'] is True
    assert entry['verified_version'] == '0.6.2.5'
    assert entry['scope'] == {'factions': ['ans']}


# --- catalog loading and alias expansion --------------------------------

def _catalog(**overrides):
    base = {
        'components': {'Stock/Focused Particle Accelerator': 'Focused Particle Accelerator',
                       'Stock/Mk600 Beam Cannon': 'Mk600 Beam Cannon'},
        'munitions': {'Stock/EA12 Chaff Decoy': 'EA12 Chaff Decoy'},
        'hulls': {'Stock/Keystone Destroyer': {
            'display': 'Keystone Destroyer', 'class': 'Keystone', 'faction': 'ans'}},
        'classes': {},
        'aliases': {},
        'version': 'test',
    }
    base.update(overrides)
    return base


def test_alias_expansions_use_display_tokens():
    catalog = _catalog(aliases={'fpa': 'Stock/Focused Particle Accelerator'})
    assert knowledge.alias_expansions(catalog) == {
        'fpa': ['focused', 'particle', 'accelerator']}


def test_alias_expansions_exclude_self_token():
    catalog = _catalog(aliases={'mk600': 'Stock/Mk600 Beam Cannon'})
    assert knowledge.alias_expansions(catalog) == {'mk600': ['beam', 'cannon']}


def test_alias_expansions_cover_hulls_and_skip_multiword_names():
    catalog = _catalog(aliases={
        'beamstone': 'Stock/Keystone Destroyer',
        'beam stone': 'Stock/Keystone Destroyer',   # multi-token name: skipped
        'ghost': 'Stock/Not A Real Id',             # unresolvable: skipped
    })
    assert knowledge.alias_expansions(catalog) == {
        'beamstone': ['keystone', 'destroyer']}


def test_search_expansions_match_shorthand():
    entries = [_entry(id='fpa-entry',
                      rule='Take at least 2 Focused Particle Accelerators')]
    expansions = {'fpa': ['focused', 'particle', 'accelerator']}
    assert knowledge.search(entries, 'FPA') == []
    results = knowledge.search(entries, 'FPA', expansions=expansions)
    assert [e['id'] for e in results] == ['fpa-entry']


def test_search_expansions_keep_original_tokens():
    entries = [
        _entry(id='literal', rule='the FPA is required'),
        _entry(id='spelled', rule='Focused Particle Accelerators required'),
    ]
    expansions = {'fpa': ['focused', 'particle', 'accelerator']}
    results = knowledge.search(entries, 'fpa required', expansions=expansions)
    assert {e['id'] for e in results} == {'literal', 'spelled'}


def test_load_catalog_missing_dir_is_empty(tmp_path):
    catalog = knowledge.load_catalog(tmp_path / 'nope')
    assert catalog['components'] == {} and catalog['hulls'] == {}
    assert knowledge.alias_expansions(catalog) == {}


def test_load_catalog_reads_all_parts(tmp_path):
    (tmp_path / 'components.toml').write_text(
        'catalog_version = "1.2.3"\n'
        '[[component]]\nid = "Stock/Widget"\ndisplay = "Widget"\n'
        '[[munition]]\nid = "Stock/Shell"\ndisplay = "Shell"\n',
        encoding='utf-8')
    (tmp_path / 'hulls.toml').write_text(
        'catalog_version = "1.2.3"\n'
        '[[hull]]\nid = "Stock/Boat"\ndisplay = "Boat"\nclass = "Dinghy"\nfaction = "osp"\n',
        encoding='utf-8')
    (tmp_path / 'aliases.toml').write_text(
        '[[alias]]\nid = "Stock/Widget"\nnames = ["WDG"]\n', encoding='utf-8')
    (tmp_path / 'classes.toml').write_text(
        '[[class]]\nname = "widgets"\nmembers = ["Stock/Widget"]\n', encoding='utf-8')
    catalog = knowledge.load_catalog(tmp_path)
    assert catalog['version'] == '1.2.3'
    assert catalog['components'] == {'Stock/Widget': 'Widget'}
    assert catalog['munitions'] == {'Stock/Shell': 'Shell'}
    assert catalog['hulls']['Stock/Boat']['class'] == 'Dinghy'
    assert catalog['classes'] == {'widgets': ['Stock/Widget']}
    assert catalog['aliases'] == {'wdg': 'Stock/Widget'}


def test_load_catalog_bad_file_degrades_to_empty_part(tmp_path):
    (tmp_path / 'components.toml').write_text('not [ valid toml', encoding='utf-8')
    (tmp_path / 'hulls.toml').write_text(
        'catalog_version = "1.2.3"\n'
        '[[hull]]\nid = "Stock/Boat"\ndisplay = "Boat"\nclass = "Dinghy"\nfaction = "osp"\n',
        encoding='utf-8')
    catalog = knowledge.load_catalog(tmp_path)
    assert catalog['components'] == {}
    assert 'Stock/Boat' in catalog['hulls']
    assert catalog['version'] == '1.2.3'


# --- status badges -------------------------------------------------------

def test_entry_badges():
    assert knowledge.entry_badges({}) == ''
    assert knowledge.entry_badges({'status': 'established'}) == ''
    assert knowledge.entry_badges({'status': 'contested'}) == knowledge.BADGE_CONTESTED
    assert knowledge.entry_badges({'patch_sensitive': True}) == knowledge.BADGE_PATCH_SENSITIVE
    both = knowledge.entry_badges({'status': 'contested', 'patch_sensitive': True})
    assert knowledge.BADGE_CONTESTED in both and knowledge.BADGE_PATCH_SENSITIVE in both


# --- plural folding -----------------------------------------------------

def test_plural_and_singular_queries_match_the_same_entry():
    entry = _entry(rule='stagger your missiles')
    assert knowledge.score_entry(knowledge.tokenize('missile'), entry) > 0
    assert knowledge.score_entry(knowledge.tokenize('missiles'), entry) > 0


def test_short_shorthand_never_folds():
    # "ans" and "vls" are live community shorthand; folding them would
    # merge them into unrelated words.
    assert knowledge.tokenize('ans vls pd gps') == ['ans', 'vls', 'pd', 'gps']


def test_double_s_words_never_fold():
    assert knowledge.tokenize('mass class') == ['mass', 'class']


# --- curated vs community tie-break -------------------------------------

def test_curated_entry_outranks_a_community_duplicate_on_a_tie():
    curated = _entry(id='fb-001', category='fleet-building',
                     rule='Take at least 2 Focused Particle Accelerators')
    duplicate = knowledge.community_entry(
        37, 'take at least 2 focused particle accelerators', 'someone')
    results = knowledge.search([duplicate, curated], 'focused particle accelerators')
    assert [e['id'] for e in results] == ['fb-001', 'ca-037']


def test_shorthand_query_ranks_the_curated_entry_first():
    """Regression: in production a community restatement of fb-001 scored
    the same and took its place, so !advice fpa served the unstructured
    copy instead of the curated entry."""
    entries = knowledge.load_entries()
    expansions = knowledge.alias_expansions(knowledge.load_catalog())
    duplicate = knowledge.community_entry(
        37, 'beams should always have at least two focused particle accelerators', 'someone')
    corpus = knowledge.active_entries(entries, [duplicate], set())
    results = knowledge.search(corpus, 'fpa', expansions=expansions)
    assert results[0]['id'] == 'fb-001'

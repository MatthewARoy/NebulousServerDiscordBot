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

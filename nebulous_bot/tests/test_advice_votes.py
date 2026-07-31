"""Pure-logic tests for community advice voting (no DB, no Discord).

Vote counting/resolution and corpus assembly live in nebulous_bot.knowledge;
text validation and the cog's corpus wiring are exercised via __new__ per
house pattern.
"""
from nebulous_bot import knowledge
from nebulous_bot.cogs.advice import AdviceCog, validate_advice_text, ADVICE_MAX_LEN


# --- resolve_votes ------------------------------------------------------

def test_resolve_below_threshold_stays_open():
    assert knowledge.resolve_votes(4, 0, threshold=5) is None
    assert knowledge.resolve_votes(0, 4, threshold=5) is None


def test_resolve_approves_at_threshold_with_majority():
    assert knowledge.resolve_votes(5, 0, threshold=5) == 'approved'
    assert knowledge.resolve_votes(5, 4, threshold=5) == 'approved'


def test_resolve_rejects_at_threshold_with_majority():
    assert knowledge.resolve_votes(0, 5, threshold=5) == 'rejected'
    assert knowledge.resolve_votes(4, 5, threshold=5) == 'rejected'


def test_resolve_tie_stays_open_even_above_threshold():
    assert knowledge.resolve_votes(7, 7, threshold=5) is None


def test_resolve_rejection_needs_more_downs_than_ups():
    # 6 up / 5 down: down met the threshold but lost the majority.
    assert knowledge.resolve_votes(6, 5, threshold=5) == 'approved'


def test_resolve_respects_custom_threshold():
    assert knowledge.resolve_votes(1, 0, threshold=1) == 'approved'
    assert knowledge.resolve_votes(1, 0, threshold=5) is None


# --- tally_voters -------------------------------------------------------

BOT = 999


def test_tally_voters_excludes_bot_seeds():
    assert knowledge.tally_voters([BOT, 1, 2], [BOT], exclude=(BOT,)) == (2, 0)


def test_tally_voters_dual_vote_cancels_out():
    # User 3 reacted with both emoji: counts for neither side.
    assert knowledge.tally_voters([1, 2, 3], [3, 4], exclude=(BOT,)) == (2, 1)


def test_tally_voters_duplicate_ids_count_once():
    assert knowledge.tally_voters([1, 1, 2], [], exclude=()) == (2, 0)


def test_tally_voters_empty():
    assert knowledge.tally_voters([], [], exclude=(BOT,)) == (0, 0)


# --- entry ids ----------------------------------------------------------

def test_community_entry_id_is_zero_padded_and_grows():
    assert knowledge.community_entry_id(7) == 'ca-007'
    assert knowledge.community_entry_id(1234) == 'ca-1234'


def test_normalize_entry_id_canonicalizes():
    assert knowledge.normalize_entry_id(' FB-3 ') == 'fb-003'
    assert knowledge.normalize_entry_id('ca-007') == 'ca-007'
    assert knowledge.normalize_entry_id('ca-1234') == 'ca-1234'


def test_normalize_entry_id_rejects_garbage():
    assert knowledge.normalize_entry_id('') is None
    assert knowledge.normalize_entry_id('fb003') is None
    assert knowledge.normalize_entry_id('toolong-001') is None


def test_community_entry_shape_matches_curated_entries():
    entry = knowledge.community_entry(3, 'Bring chaff', 'Larc', source_url='https://x')
    assert entry['id'] == 'ca-003'
    assert entry['category'] == knowledge.COMMUNITY_CATEGORY
    assert entry['tags'] == []
    # Searchable like any curated entry:
    assert knowledge.search([entry], 'chaff') == [entry]


# --- corpus assembly ----------------------------------------------------

def _entry(eid, rule='r'):
    return {'id': eid, 'rule': rule, 'tags': [], 'category': 'test'}


def test_active_entries_merges_and_filters_removed():
    curated = [_entry('fb-001'), _entry('fb-002')]
    community = [_entry('ca-001'), _entry('ca-002')]
    result = knowledge.active_entries(curated, community, {'fb-002', 'ca-001'})
    assert [e['id'] for e in result] == ['fb-001', 'ca-002']


def test_cog_corpus_uses_community_and_removed_state():
    cog = AdviceCog.__new__(AdviceCog)
    cog.entries = [_entry('fb-001', 'curated tip')]
    cog.community = {5: _entry('ca-005', 'community tip')}
    cog.removed_ids = set()
    assert {e['id'] for e in cog._corpus()} == {'fb-001', 'ca-005'}
    cog.removed_ids = {'fb-001'}
    assert {e['id'] for e in cog._corpus()} == {'ca-005'}


# --- submission text validation -----------------------------------------

def test_validate_advice_text_happy_path_collapses_whitespace():
    cleaned, error = validate_advice_text('  Keep   radar\non at all times  ')
    assert error is None
    assert cleaned == 'Keep radar on at all times'


def test_validate_advice_text_rejects_empty_and_short():
    assert validate_advice_text(None)[0] is None
    assert validate_advice_text('   ')[0] is None
    assert validate_advice_text('too short')[1] is not None


def test_validate_advice_text_rejects_overlong():
    cleaned, error = validate_advice_text('x' * (ADVICE_MAX_LEN + 1))
    assert cleaned is None
    assert 'too long' in error

"""Pure-logic tests for community advice voting (no DB, no Discord).

Vote counting/resolution and corpus assembly live in nebulous_bot.knowledge;
text validation and the cog's corpus wiring are exercised via __new__ per
house pattern.
"""
import asyncio
from types import SimpleNamespace

from nebulous_bot import knowledge
from nebulous_bot.cogs.advice import (
    AdviceCog, find_existing_advice, format_result_field, validate_advice_text,
    ADVICE_MAX_LEN, MAX_OPEN_BALLOTS, MAX_OPEN_BALLOTS_PER_GUILD)


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


# --- result rendering ---------------------------------------------------

def test_result_field_carries_the_entry_id():
    entry = knowledge.community_entry(7, 'keep your radar on', 'Someone')
    name, value = format_result_field(entry)
    assert 'keep your radar on' in name
    assert value.endswith('`ca-007`')


def test_result_field_credit_link_cannot_be_hijacked():
    entry = knowledge.community_entry(
        1, 'some advice text', 'evil](https://evil.example) x',
        source_url='https://discord.com/channels/1/2/3')
    credit_line = format_result_field(entry)[1].splitlines()[-1]
    # Discord renders the escaped brackets as literal text, so strip them:
    # exactly one masked link is left, and it points at the real source.
    unescaped = credit_line.replace('\\]', '').replace('\\[', '')
    assert unescaped.count('](') == 1
    assert unescaped.endswith('](https://discord.com/channels/1/2/3) · `ca-001`')


def test_result_field_leaves_curated_text_verbatim():
    entry = {
        'id': 'fb-001',
        'rule': 'Take at least 2 Focused Particle Accelerators',
        'situation': 'Fitting the ANS Mk600 Beam Cannon',
        'reason': 'Beams deal many small ticks of damage',
        'author': 'Davaned',
        'source_url': 'https://discord.com/channels/1/2/3',
        'category': 'fleet-building',
    }
    name, value = format_result_field(entry)
    assert name.endswith('Take at least 2 Focused Particle Accelerators')
    assert '*When:* Fitting the ANS Mk600 Beam Cannon' in value
    assert '*Why:* Beams deal many small ticks of damage' in value
    assert value.endswith('— [Davaned](https://discord.com/channels/1/2/3) · `fb-001`')


# --- restore plumbing ---------------------------------------------------

def test_community_entry_pk_inverts_the_public_id():
    assert knowledge.community_entry_pk('ca-007') == 7
    assert knowledge.community_entry_pk('CA-1234') == 1234


def test_community_entry_pk_rejects_curated_ids():
    assert knowledge.community_entry_pk('fb-001') is None
    assert knowledge.community_entry_pk('nonsense') is None


# --- duplicate detection sees tombstones --------------------------------

def _curated(eid='fb-001', rule='Take at least 2 Focused Particle Accelerators'):
    return {'id': eid, 'rule': rule, 'tags': [], 'category': 'fleet-building'}


def test_find_existing_advice_matches_a_tombstoned_curated_entry():
    # The cog passes self.entries, which keeps tombstoned entries, so the
    # exact words of voted-out advice cannot be voted straight back in.
    found = find_existing_advice([_curated()], [],
                                 '  take   at LEAST 2 focused particle accelerators ')
    assert found['id'] == 'fb-001'


def test_find_existing_advice_ignores_different_wording():
    assert find_existing_advice([_curated()], [], 'Bring two FPAs for beams') is None


# --- ballot budget ------------------------------------------------------

def _ballot(message_id, guild_id):
    return {'pk': message_id, 'message_id': message_id, 'guild_id': guild_id, 'kind': 'add'}


def _cog_with_ballots(rows):
    cog = AdviceCog.__new__(AdviceCog)
    cog.pending = {row['message_id']: row for row in rows}
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=BOT))
    return cog


def test_one_guild_cannot_take_the_whole_ballot_budget():
    cog = _cog_with_ballots([_ballot(i, 111) for i in range(MAX_OPEN_BALLOTS_PER_GUILD)])
    assert cog._at_capacity(111) is True
    assert cog._at_capacity(222) is False


def test_global_cap_still_applies_across_guilds():
    # One ballot each in many guilds: every guild is under its own share,
    # but the global bound is reached.
    cog = _cog_with_ballots([_ballot(i, 1000 + i) for i in range(MAX_OPEN_BALLOTS)])
    assert cog._at_capacity(999) is True


# --- vote withdrawal ----------------------------------------------------

def _tally_spy(cog):
    seen = []

    async def fake_tally(message_id):
        seen.append(message_id)

    cog._tally = fake_tally
    return seen


def test_withdrawing_a_vote_re_tallies_the_ballot():
    cog = _cog_with_ballots([_ballot(99, 111)])
    seen = _tally_spy(cog)
    payload = SimpleNamespace(user_id=42, emoji=knowledge.DOWN_EMOJI, message_id=99)
    asyncio.run(cog.on_raw_reaction_remove(payload))
    assert seen == [99]


def test_vote_events_ignore_the_bots_own_reactions():
    cog = _cog_with_ballots([_ballot(99, 111)])
    seen = _tally_spy(cog)
    payload = SimpleNamespace(user_id=BOT, emoji=knowledge.UP_EMOJI, message_id=99)
    asyncio.run(cog.on_raw_reaction_add(payload))
    assert seen == []


def test_vote_events_ignore_messages_that_are_not_ballots():
    cog = _cog_with_ballots([_ballot(99, 111)])
    seen = _tally_spy(cog)
    payload = SimpleNamespace(user_id=42, emoji=knowledge.UP_EMOJI, message_id=12345)
    asyncio.run(cog.on_raw_reaction_remove(payload))
    assert seen == []

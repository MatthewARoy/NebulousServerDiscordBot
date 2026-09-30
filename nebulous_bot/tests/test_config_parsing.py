"""Pure-logic tests for config helpers: env parsing + test-harness gate."""
import pytest

from nebulous_bot.config import parse_bool, parse_id_set, harness_command_allowed


@pytest.mark.parametrize('value', ['false', 'FALSE', '0', 'no', ' off '])
def test_rollout_flag_disables_intent(value):
    assert parse_bool(value) is False


@pytest.mark.parametrize('value', ['true', 'TRUE', '1', 'yes', ' on '])
def test_rollout_flag_enables_compatibility(value):
    assert parse_bool(value) is True


@pytest.mark.parametrize('value', ['', 'flase', 'enabled'])
def test_rollout_flag_rejects_ambiguous_values(value):
    with pytest.raises(ValueError):
        parse_bool(value)


def test_parse_id_set_commas_and_spaces():
    assert parse_id_set('123, 456 789') == frozenset({123, 456, 789})


def test_parse_id_set_empty_is_empty():
    assert parse_id_set('') == frozenset()
    assert parse_id_set('  ,  ') == frozenset()


def test_parse_id_set_drops_garbage_instead_of_raising():
    assert parse_id_set('123, notanid, 45.6, 789') == frozenset({123, 789})


BOTS = frozenset({100})
GUILDS = frozenset({200})


def test_gate_allows_listed_bot_in_listed_guild():
    assert harness_command_allowed(100, 200, 999, BOTS, GUILDS)


def test_harness_fails_closed_on_empty_allowlists():
    assert not harness_command_allowed(100, 200, 999, frozenset(), GUILDS)
    assert not harness_command_allowed(100, 200, 999, BOTS, frozenset())


def test_harness_rejects_wrong_bot_wrong_guild_dms_and_self():
    assert not harness_command_allowed(101, 200, 999, BOTS, GUILDS)   # unlisted bot
    assert not harness_command_allowed(100, 201, 999, BOTS, GUILDS)   # unlisted guild
    assert not harness_command_allowed(100, None, 999, BOTS, GUILDS)  # DM
    assert not harness_command_allowed(100, 200, 100, BOTS, GUILDS)   # the bot itself

"""Tests for the !nextgame argument parser.

The parser was extracted from the inline command body during the cog split;
these tests pin down the existing behavior, including every accepted token
alias (the `-skip` alias was added in 2.4.x and regressed once before).
"""
import pytest

from nebulous_bot.cogs.nextgame import parse_nextgame_args


def test_empty_args():
    parsed = parse_nextgame_args("")
    assert parsed.ptb_only is False
    assert parsed.modded_only is False
    assert parsed.newplayer_only is False
    assert parsed.lobby_only is False
    assert parsed.skip_current_lobbies is False


def test_ptb():
    assert parse_nextgame_args("ptb").ptb_only is True


def test_ptb_must_be_exact_token():
    # 'ptbx' or 'ptb-only' must not match
    assert parse_nextgame_args("ptbx").ptb_only is False
    assert parse_nextgame_args("ptb-only").ptb_only is False


@pytest.mark.parametrize("token", ['modded', 'mod', 'mfc'])
def test_modded_aliases(token):
    assert parse_nextgame_args(token).modded_only is True


@pytest.mark.parametrize("token", ['newplayer', 'new-player', 'np', 'beginner'])
def test_newplayer_aliases(token):
    assert parse_nextgame_args(token).newplayer_only is True


@pytest.mark.parametrize("token", ['lobby', '--lobby', '-l'])
def test_lobby_aliases(token):
    assert parse_nextgame_args(token).lobby_only is True


@pytest.mark.parametrize("token", ['--skip', '-skip', '-s', 'skip'])
def test_skip_aliases(token):
    assert parse_nextgame_args(token).skip_current_lobbies is True


def test_combined_modes():
    parsed = parse_nextgame_args("ptb modded lobby --skip")
    assert parsed.ptb_only is True
    assert parsed.modded_only is True
    assert parsed.newplayer_only is False
    assert parsed.lobby_only is True
    assert parsed.skip_current_lobbies is True


def test_case_insensitive_and_whitespace():
    parsed = parse_nextgame_args("  PTB   NewPlayer  -SKIP ")
    assert parsed.ptb_only is True
    assert parsed.newplayer_only is True
    assert parsed.skip_current_lobbies is True


def test_unknown_tokens_ignored():
    parsed = parse_nextgame_args("banana --frobnicate")
    assert parsed == parse_nextgame_args("")

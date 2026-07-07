"""Tests for the !listservers filter-argument parser.

The parser was extracted from the inline command body during the cog split;
these tests pin down the existing behavior, including the quirks (later
status/region/mode tokens overwrite earlier ones, unknown tokens are
ignored).
"""
from nebulous_bot.cogs.servers import parse_listservers_filters


def test_empty_args():
    filters, show_all, ptb_only = parse_listservers_filters("")
    assert filters == {}
    assert show_all is False
    assert ptb_only is False


def test_ptb_only():
    filters, show_all, ptb_only = parse_listservers_filters("ptb")
    assert filters == {}
    assert show_all is False
    assert ptb_only is True


def test_all():
    filters, show_all, ptb_only = parse_listservers_filters("all")
    assert filters == {}
    assert show_all is True
    assert ptb_only is False


def test_open():
    filters, _, _ = parse_listservers_filters("open")
    assert filters == {'open_lobby': True}


def test_status_lobby_and_region():
    filters, show_all, ptb_only = parse_listservers_filters("lobby us")
    assert filters == {'status': 'lobby', 'region': 'us'}
    assert show_all is False
    assert ptb_only is False


def test_ingame_overrides_lobby():
    # Both present: the 'ingame' check runs after 'lobby' and wins.
    filters, _, _ = parse_listservers_filters("lobby ingame")
    assert filters['status'] == 'in_game'


def test_eu_overrides_us():
    filters, _, _ = parse_listservers_filters("us eu")
    assert filters['region'] == 'eu'


def test_casual_overrides_competitive():
    filters, _, _ = parse_listservers_filters("competitive casual")
    assert filters['game_mode'] == 'casual'


def test_case_insensitive():
    filters, show_all, ptb_only = parse_listservers_filters("PTB Open EU")
    assert ptb_only is True
    assert filters == {'open_lobby': True, 'region': 'eu'}
    assert show_all is False


def test_unknown_tokens_ignored():
    filters, show_all, ptb_only = parse_listservers_filters("banana ptbx opened")
    assert filters == {}
    assert show_all is False
    assert ptb_only is False


def test_combined_ptb_all():
    filters, show_all, ptb_only = parse_listservers_filters("ptb all")
    assert filters == {}
    assert show_all is True
    assert ptb_only is True

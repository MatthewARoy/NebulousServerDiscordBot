"""Tests for the !nextgame newplayer queue mode."""
from nebulous_bot.steam_api import SteamAPI

from .test_waiter_modes import make_monitor, lobby


def np_lobby(name, players=4, capacity=8):
    server = lobby(name, players, capacity)
    server['is_new_player'] = True
    return server


def test_newplayer_only_matches_only_newplayer_servers():
    monitor = make_monitor([
        np_lobby('ERI New Player (US EAST)'),
        lobby('Veteran Stack', 4, 8),
    ])
    matched = monitor.find_matching_servers_for_notification(newplayer_only=True)
    assert {s['name'] for s in matched} == {'ERI New Player (US EAST)'}


def test_no_filter_still_returns_all_ready_servers():
    monitor = make_monitor([
        np_lobby('ERI New Player (US EAST)'),
        lobby('Veteran Stack', 4, 8),
    ])
    matched = monitor.find_matching_servers_for_notification()
    assert len(matched) == 2


def test_newplayer_queue_coexists_with_other_modes_for_same_user():
    monitor = make_monitor([])
    monitor.add_next_game_waiter(42, 100, 'user#1')
    monitor.add_next_game_waiter(42, 100, 'user#1', newplayer_only=True)

    assert monitor.is_user_waiting_for_next_game(42, ptb_only=False, newplayer_only=True) is True
    assert monitor.is_user_waiting_for_next_game(42, ptb_only=False, newplayer_only=False) is True
    assert monitor.get_next_game_waiter(42, newplayer_only=True)['newplayer_only'] is True
    assert monitor.get_next_game_waiters_count() == 1

    # cancel removes all of a user's modes, including newplayer
    assert monitor.remove_next_game_waiter(42) is True
    assert monitor.is_user_waiting_for_next_game(42) is False


def test_newplayer_stacks_with_modded_filter():
    both = np_lobby('Modded New Player Night')
    both['is_modded'] = True
    monitor = make_monitor([
        both,
        np_lobby('Vanilla New Player'),
        lobby('Modded Veterans', 4, 8, modded=True),
    ])
    matched = monitor.find_matching_servers_for_notification(modded_only=True, newplayer_only=True)
    assert {s['name'] for s in matched} == {'Modded New Player Night'}


def test_name_detection_patterns():
    api = SteamAPI()
    assert api._is_new_player_server('ERI Official New Player (US EAST)') is True
    assert api._is_new_player_server('NEWPLAYER FRIENDLY') is True
    assert api._is_new_player_server('Beginner Arena') is True
    assert api._is_new_player_server('newbie night') is True
    assert api._is_new_player_server('Veteran Stack') is False
    assert api._is_new_player_server('') is False

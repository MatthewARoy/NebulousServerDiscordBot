"""Tests for modded-aware matching and the next-game waiter store."""
from nebulous_bot.server_monitor import ServerMonitor


def make_monitor(servers):
    # Bypass __init__: it constructs StatisticsService, which hits the DB
    # (CI runs no migrations before pytest). The methods under test only need
    # these three attributes.
    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.cached_servers = servers
    monitor.next_game_waiters = {}
    monitor.recent_debrief_transitions = {}
    return monitor


def lobby(name, players, capacity, *, modded=False, ptb=False):
    return {
        'name': name, 'status': 'lobby', 'players': players,
        'map_capacity': capacity, 'is_modded': modded, 'is_test_branch': ptb,
        'address': '1.2.3.4', 'gameport': 0, 'id': name,
    }


def test_modded_only_returns_only_modded_ready_servers():
    monitor = make_monitor([
        lobby('Modded Lobby', 4, 8, modded=True),
        lobby('Vanilla Lobby', 4, 8, modded=False),
    ])
    matched = monitor.find_matching_servers_for_notification(modded_only=True)
    names = {s['name'] for s in matched}
    assert names == {'Modded Lobby'}


def test_no_filter_returns_all_ready_servers():
    monitor = make_monitor([
        lobby('Modded Lobby', 4, 8, modded=True),
        lobby('Vanilla Lobby', 4, 8, modded=False),
    ])
    matched = monitor.find_matching_servers_for_notification()
    names = {s['name'] for s in matched}
    assert names == {'Modded Lobby', 'Vanilla Lobby'}


def debrief(name, *, modded=False):
    return {
        'name': name, 'status': 'debrief', 'players': 0,
        'map_capacity': 8, 'is_modded': modded, 'is_test_branch': False,
        'address': '1.2.3.4', 'gameport': 0, 'id': name,
    }


def test_modded_only_filters_debrief_servers():
    monitor = make_monitor([
        debrief('Modded Debrief', modded=True),
        debrief('Vanilla Debrief', modded=False),
    ])
    matched = monitor.find_matching_servers_for_notification(modded_only=True)
    assert {s['name'] for s in matched} == {'Modded Debrief'}


def test_modded_and_normal_waiters_coexist_for_same_user():
    monitor = make_monitor([])
    monitor.add_next_game_waiter(42, 100, 'user#1', modded_only=False)
    monitor.add_next_game_waiter(42, 100, 'user#1', modded_only=True)

    assert monitor.is_user_waiting_for_next_game(42, ptb_only=False, modded_only=True) is True
    assert monitor.is_user_waiting_for_next_game(42, ptb_only=False, modded_only=False) is True
    assert monitor.get_next_game_waiter(42, modded_only=True)['modded_only'] is True
    assert monitor.get_next_game_waiter(42, modded_only=False)['modded_only'] is False

    # is_user_waiting with ptb_only=None means "any mode"
    assert monitor.is_user_waiting_for_next_game(42) is True

    # cancel removes all of a user's modes
    assert monitor.remove_next_game_waiter(42) is True
    assert monitor.is_user_waiting_for_next_game(42) is False


def test_get_next_game_waiters_count_dedupes_user_across_modes():
    monitor = make_monitor([])
    monitor.add_next_game_waiter(42, 100, 'user#1', modded_only=False)
    monitor.add_next_game_waiter(42, 100, 'user#1', modded_only=True)
    assert monitor.get_next_game_waiters_count() == 1

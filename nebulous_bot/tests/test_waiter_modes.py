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

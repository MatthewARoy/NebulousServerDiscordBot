"""Population snapshots must count everyone on a listed server.

They were once summed over the display-filtered list, so one bot or a
"private"-style name removed every person on that server from /graph.
"""
import asyncio
from unittest.mock import patch

from nebulous_bot.server_monitor import ServerMonitor
from nebulous_bot.statistics_tracker import (
    PlayerCountTracker,
    StatisticsService,
    human_players,
    summarize_servers,
)
from nebulous_bot.steam_api import SteamAPI


api = SteamAPI()


def server(players=0, bots=0, status='lobby', name='Public'):
    return {'players': players, 'bots': bots, 'status': status, 'name': name}


def test_human_players_removes_bots_and_never_goes_negative():
    assert human_players(server(players=6, bots=2)) == 4
    assert human_players(server(players=1, bots=3)) == 0
    assert human_players({}) == 0


def test_people_on_servers_the_display_filter_hides_are_counted():
    with_bot = server(players=6, bots=2, status='in_game')
    private = server(players=3, name='Clan Only Private Server')
    assert api.passes_default_filter(with_bot) is False
    assert api.passes_default_filter(private) is False

    totals = summarize_servers([server(players=5), with_bot, private])

    assert totals['total_players'] == 5 + 4 + 3
    assert totals['total_servers'] == 3


def test_servers_without_people_do_not_inflate_server_totals():
    totals = summarize_servers([
        server(status='lobby'),
        server(status='in_game'),
        server(players=2, bots=2, status='in_game'),
        server(players=1, status='lobby'),
        server(players=4, status='in_game'),
        server(players=4, status='debrief'),
    ])

    assert totals == {
        'total_players': 9,
        'total_servers': 3,
        'open_lobbies': 1,
        'games_in_progress': 1,
    }


def test_no_servers_is_a_zero_snapshot():
    assert summarize_servers([]) == {
        'total_players': 0,
        'total_servers': 0,
        'open_lobbies': 0,
        'games_in_progress': 0,
    }


def test_snapshot_writes_the_summarized_totals():
    tracker = PlayerCountTracker()
    servers = [server(players=6, bots=2, status='in_game')]

    with patch('nebulous_bot.statistics_tracker.PlayerSnapshot.objects.create') as create:
        tracker.take_snapshot(servers)

    create.assert_called_once_with(
        total_players=4, total_servers=1, open_lobbies=0, games_in_progress=1,
        steam_concurrent=None,
    )


def make_service():
    service = StatisticsService.__new__(StatisticsService)

    class FakeGames:
        seen = None

        def ensure_recovered(self):
            pass

        def update_server_state(self, state):
            self.seen = (self.seen or []) + [state]

    class FakePlayers:
        seen = None
        steam = None
        due = True

        def should_take_snapshot(self):
            return self.due

        def take_snapshot(self, servers, steam_concurrent=None):
            self.seen = servers
            self.steam = steam_concurrent

    service.game_tracker = FakeGames()
    service.player_tracker = FakePlayers()
    return service


def test_update_snapshots_all_servers_but_tracks_games_on_the_filtered_list():
    service = make_service()
    filtered = [server(players=5)]
    everything = filtered + [server(players=6, bots=2)]

    service.update(filtered, everything)

    assert service.player_tracker.seen is everything
    assert service.game_tracker.seen == filtered


def test_update_keeps_an_empty_all_server_list_rather_than_falling_back():
    service = make_service()

    service.update([server(players=5)], [])

    assert service.player_tracker.seen == []


def make_monitor(steam_count=47):
    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.statistics_service = make_service()
    monitor.cached_servers = [server(players=5)]
    monitor.cached_all_servers = monitor.cached_servers + [server(players=6, bots=2)]

    class FakeSteam:
        calls = 0

        async def get_concurrent_players(self):
            self.calls += 1
            return steam_count

    monitor.steam_api = FakeSteam()
    return monitor


def test_monitor_hands_statistics_both_server_caches():
    monitor = make_monitor()

    asyncio.run(monitor._update_statistics())

    assert monitor.statistics_service.player_tracker.seen is monitor.cached_all_servers
    assert monitor.statistics_service.game_tracker.seen == monitor.cached_servers


def test_monitor_passes_steam_count_when_a_snapshot_is_due():
    monitor = make_monitor(steam_count=47)

    asyncio.run(monitor._update_statistics())

    assert monitor.steam_api.calls == 1
    assert monitor.statistics_service.player_tracker.steam == 47


def test_monitor_skips_the_steam_call_between_snapshots():
    monitor = make_monitor()
    monitor.statistics_service.player_tracker.due = False

    asyncio.run(monitor._update_statistics())

    assert monitor.steam_api.calls == 0
    assert monitor.statistics_service.game_tracker.seen == monitor.cached_servers


def test_failed_steam_count_still_writes_the_snapshot():
    tracker = PlayerCountTracker()

    with patch('nebulous_bot.statistics_tracker.PlayerSnapshot.objects.create') as create:
        tracker.take_snapshot([server(players=5)], None)

    assert create.call_args.kwargs['total_players'] == 5
    assert create.call_args.kwargs['steam_concurrent'] is None

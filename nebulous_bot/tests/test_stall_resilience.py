"""Pure-logic tests for the failure modes a starved VM exposes.

Production evidence (2026-09-09 17:32 PST, mid-stall): a
"Server rules queries timed out" warning was followed within 90 s by two
games being finalized and two fresh games being created on the *same two
servers*. The A2S sweep had expired, every server was rebuilt without
rules, and rules-less servers defaulted to status='lobby' — which the
statistics state machine reads as "the game ended".

These tests pin the three guards that stop a stall from becoming bad data.
ServerMonitor is built via __new__ per house pattern, with just the
attributes these paths touch.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from nebulous_bot.server_monitor import ServerMonitor
from nebulous_bot.steam_api import SteamAPI


# --- status_known on enhanced server data -------------------------------

def _enhanced(rules):
    return SteamAPI.__new__(SteamAPI)._create_enhanced_server_data(
        {'steamid': '1', 'addr': '1.2.3.4:27015', 'map': 'Gold Rush'},
        'srv', 4, rules,
    )


def test_rules_answer_marks_status_known():
    server = _enhanced({'inprogress': '1'})
    assert server['status_known'] is True
    assert server['status'] == 'in_game'


def test_missing_rules_marks_status_unknown():
    server = _enhanced(None)
    assert server['status_known'] is False


def test_empty_rules_marks_status_unknown():
    # _query_server_rules falls back to the raw A2S_RULES dict, which can
    # be {} when the reply is empty or fails to parse. That is a
    # non-answer too, not an observed lobby.
    assert _enhanced({})['status_known'] is False


def test_missing_rules_still_displays_as_lobby():
    # Display must not change: embeds and get_open_lobbies keep reading
    # 'lobby' as before. Only transition consumers gate on status_known.
    assert _enhanced(None)['status'] == 'lobby'


# --- _track_game_start_times skips unknown-status servers ---------------

def _monitor():
    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.game_start_times = {}
    monitor.recent_debrief_transitions = {}
    return monitor


def test_unknown_status_does_not_record_a_transition():
    monitor = _monitor()
    monitor.game_start_times['s1'] = {
        'transition_time': datetime.now(timezone.utc),
        'previous_status': 'in_game',
        'current_state': 'in_game',
        'server_name': 'srv',
    }
    asyncio.run(monitor._track_game_start_times(
        [{'id': 's1', 'name': 'srv', 'status': 'lobby', 'status_known': False}]
    ))
    # The blind sweep must leave the tracked state exactly as it was.
    assert monitor.game_start_times['s1']['previous_status'] == 'in_game'


def test_known_status_still_records_a_transition():
    monitor = _monitor()
    asyncio.run(monitor._track_game_start_times(
        [{'id': 's1', 'name': 'srv', 'status': 'in_game', 'status_known': True}]
    ))
    assert monitor.game_start_times['s1']['previous_status'] == 'in_game'


def test_absent_status_known_defaults_to_trusting_the_status():
    # Servers built elsewhere (tests, fixtures) have no status_known key and
    # must keep their existing behaviour.
    monitor = _monitor()
    asyncio.run(monitor._track_game_start_times(
        [{'id': 's1', 'name': 'srv', 'status': 'in_game'}]
    ))
    assert monitor.game_start_times['s1']['previous_status'] == 'in_game'


# --- a failed Steam sweep must not be published as fresh ----------------

def _monitor_with_cache(servers, age_seconds, sweep_result):
    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.cached_servers = list(servers)
    monitor.cached_all_servers = list(servers)
    monitor.last_update = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    monitor.stable_version = 'v1'
    monitor.game_start_times = {}
    monitor.recent_debrief_transitions = {}

    class FakeSteam:
        async def get_game_servers(self):
            return sweep_result

        def passes_default_filter(self, server):
            return True

    monitor.steam_api = FakeSteam()
    return monitor


def test_failed_sweep_keeps_the_last_known_list():
    monitor = _monitor_with_cache([{'id': 's1', 'players': 4}], 30, None)
    asyncio.run(monitor._update_server_list())
    assert monitor.cached_servers == [{'id': 's1', 'players': 4}]


def test_failed_sweep_does_not_refresh_the_timestamp():
    # The status embed's "updated" stamp must go stale rather than lie.
    monitor = _monitor_with_cache([{'id': 's1', 'players': 4}], 30, None)
    before = monitor.last_update
    asyncio.run(monitor._update_server_list())
    assert monitor.last_update == before


def test_a_genuinely_empty_result_is_still_published():
    # Steam answering "no servers" is real at 4am and must not be confused
    # with the call having failed.
    monitor = _monitor_with_cache([{'id': 's1', 'players': 4}], 30, [])
    monitor._recalculate_test_branch_flags = lambda: None
    asyncio.run(monitor._update_server_list())
    assert monitor.cached_servers == []
    assert (datetime.now(timezone.utc) - monitor.last_update).total_seconds() < 1


# --- tracked-message eviction after a sustained 403 ---------------------

@pytest.fixture
def forbidden_monitor(monkeypatch):
    import discord

    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.formatter = object()

    class FakeEmbed:
        title = "Open Lobbies"
        footer = None

    class FakeMessage:
        id = 123
        embeds = [FakeEmbed()]

        async def edit(self, **kwargs):
            raise discord.Forbidden(_FakeResponse(), 'no')

    class _FakeResponse:
        status = 403
        reason = 'Forbidden'

    monitor.get_open_lobbies = lambda: []
    monkeypatch.setattr(
        monitor, 'formatter',
        type('F', (), {'create_lobby_list_embed': staticmethod(lambda *a, **k: FakeEmbed())})(),
        raising=False,
    )
    monitor.last_update = datetime.now(timezone.utc)
    return monitor, FakeMessage()


def test_a_single_forbidden_keeps_the_message(forbidden_monitor):
    monitor, message = forbidden_monitor
    msg_info = {'message': message}
    result = asyncio.run(monitor._refresh_tracked_message(None, 9, 0, msg_info))
    assert result.get('removed') is not True
    assert msg_info['forbidden_streak'] == 1


def test_a_sustained_forbidden_streak_evicts_the_message(forbidden_monitor):
    monitor, message = forbidden_monitor
    msg_info = {'message': message}
    for _ in range(ServerMonitor.FORBIDDEN_EVICT_AFTER - 1):
        result = asyncio.run(monitor._refresh_tracked_message(None, 9, 0, msg_info))
        assert result.get('removed') is not True
    result = asyncio.run(monitor._refresh_tracked_message(None, 9, 0, msg_info))
    assert result['removed'] is True


# --- statistics never acts on a rules-blind server ----------------------

def _tracker():
    from nebulous_bot.statistics_tracker import GameSessionTracker

    tracker = GameSessionTracker.__new__(GameSessionTracker)
    tracker.active_sessions = {'s1': 42}
    return tracker


def test_unknown_status_does_not_finalize_an_active_session():
    # The guard must return before any ORM access, so the session for s1
    # stays attached and no GameSession row is touched.
    tracker = _tracker()
    result = tracker.update_server_state(
        {'id': 's1', 'name': 'srv', 'status': 'lobby', 'status_known': False}
    )
    assert result is None
    assert tracker.active_sessions == {'s1': 42}

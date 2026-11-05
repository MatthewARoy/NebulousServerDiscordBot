"""Game sessions must survive their server leaving the display-filtered list.

The filter drops a server the moment its last player leaves, so tracking only
the filtered list never saw those games end. The row stayed open until someone
returned: a later lobby stamped that moment as the game's end, and a later game
merged into the old row.

These tests run the real tracker and the real GameSession model logic. Only the
database calls are replaced.
"""
from datetime import datetime, timedelta, timezone

import pytest
from django.db import models

from nebulous_bot.models import GameSession
from nebulous_bot.statistics_tracker import GameSessionTracker, StatisticsService
from nebulous_bot.steam_api import SteamAPI

api = SteamAPI()

POLL = timedelta(seconds=30)
GRACE = GameSessionTracker.ABANDON_GRACE
START = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def game_server(players=4, status='in_game', bots=0, name='Public', status_known=True, id='A'):
    return {
        'id': id, 'address': f'{id}:1', 'name': name, 'map': 'Arroyo', 'players': players,
        'bots': bots, 'status': status, 'status_known': status_known,
    }


class FakeRows:
    """Stands in for one queryset; supports what the tracker calls."""

    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def update(self, **fields):
        for row in self.rows:
            for name, value in fields.items():
                setattr(row, name, value)
        return len(self.rows)


class FakeManager:
    """In-memory GameSession.objects that counts every database touch."""

    def __init__(self):
        self.rows = []
        self.queries = 0

    def create(self, **fields):
        self.queries += 1
        row = GameSession(id=len(self.rows) + 1, **fields)
        self.rows.append(row)
        return row

    def get(self, id):
        self.queries += 1
        for row in self.rows:
            if row.id == id:
                return row
        raise GameSession.DoesNotExist

    def filter(self, **conditions):
        self.queries += 1

        def matches(row):
            for key, wanted in conditions.items():
                if key.endswith('__lt'):
                    if not getattr(row, key[:-4]) < wanted:
                        return False
                elif getattr(row, key) != wanted:
                    return False
            return True

        return FakeRows([row for row in self.rows if matches(row)])


class World:
    def __init__(self, manager):
        self.games = manager
        self.now = START
        self.service = StatisticsService()
        self.service.game_tracker._recovery_pending = False
        self.service.player_tracker.take_snapshot = lambda *args: None

    @property
    def tracker(self):
        return self.service.game_tracker

    def poll(self, *listed):
        """One monitor cycle, with the real display filter, then 30 s pass."""
        filtered = [s for s in listed if api.passes_default_filter(s)]
        self.service.update(filtered, list(listed))
        self.now += POLL

    def repeat(self, duration, *listed):
        for _ in range(int(duration / POLL)):
            self.poll(*listed)

    def poll_past_grace(self, *listed):
        self.repeat(GRACE + POLL, *listed)


@pytest.fixture
def world(monkeypatch):
    manager = FakeManager()
    world = World(manager)
    monkeypatch.setattr(GameSession, 'objects', manager)
    monkeypatch.setattr(models.Model, 'save', lambda self, *args, **kwargs: None)
    monkeypatch.setattr('nebulous_bot.statistics_tracker.django_timezone.now', lambda: world.now)
    return world


# ---- the reported defect ----

def test_emptied_server_ends_the_game_when_people_left_not_when_someone_returns(world):
    world.repeat(timedelta(minutes=2), game_server())
    left_at = world.now

    # Empty for three hours, still reporting in_game.
    world.repeat(timedelta(hours=3), game_server(players=0))
    world.poll(game_server(players=1, status='lobby'))

    game = world.games.rows[0]
    assert game.game_end == left_at
    assert game.duration_seconds == 120
    assert game.is_valid_game is False
    assert game.is_ongoing is False
    assert world.tracker.active_sessions == {}


def test_game_that_filled_the_five_minutes_before_emptying_still_counts(world):
    world.repeat(timedelta(minutes=20), game_server())
    world.poll_past_grace(game_server(players=0))

    game = world.games.rows[0]
    assert game.duration_seconds == 1200
    assert game.is_valid_game is True


def test_new_game_after_an_emptied_server_gets_its_own_row(world):
    world.repeat(timedelta(minutes=10), game_server())
    first_end = world.now
    world.repeat(timedelta(hours=1), game_server(players=0))
    new_start = world.now

    world.poll(game_server(players=6))

    assert len(world.games.rows) == 2
    old, new = world.games.rows
    assert old.game_end == first_end
    assert old.max_players_during_game == 4
    assert new.game_start == new_start
    assert new.is_ongoing is True


def test_empty_lobby_closes_the_game_at_once(world):
    world.repeat(timedelta(minutes=10), game_server())
    ended = world.now

    world.poll(game_server(players=0, status='lobby'))

    game = world.games.rows[0]
    assert game.game_end == ended
    assert game.is_ongoing is False
    assert world.tracker.active_sessions == {}


def test_lobby_after_a_short_empty_gap_ends_when_the_gap_began(world):
    world.repeat(timedelta(minutes=3), game_server())
    left_at = world.now
    world.repeat(timedelta(minutes=2), game_server(players=0))

    world.poll(game_server(players=2, status='lobby'))

    game = world.games.rows[0]
    assert game.game_end == left_at
    assert game.duration_seconds == 180
    assert game.is_valid_game is False


def test_debrief_after_a_short_empty_gap_ends_when_the_gap_began(world):
    world.repeat(timedelta(minutes=10), game_server())
    left_at = world.now
    world.repeat(timedelta(minutes=2), game_server(players=0))

    world.poll(game_server(players=2, status='debrief'))

    assert world.games.rows[0].game_end == left_at


# ---- one game must not be split ----

def test_player_returning_within_the_grace_period_continues_the_same_game(world):
    world.repeat(timedelta(minutes=10), game_server())
    world.repeat(GRACE - 2 * POLL, game_server(players=0))
    world.repeat(timedelta(minutes=10), game_server())
    world.poll(game_server(status='debrief'))

    assert len(world.games.rows) == 1
    game = world.games.rows[0]
    assert game.duration_seconds == (10 * 60) + (GRACE - 2 * POLL).total_seconds() + (10 * 60)
    assert world.tracker._unoccupied_since == {}


def test_a_new_empty_gap_gets_a_fresh_grace_period(world):
    world.repeat(timedelta(minutes=1), game_server())
    world.repeat(GRACE - 2 * POLL, game_server(players=0))
    world.repeat(timedelta(minutes=1), game_server())
    world.repeat(GRACE - 2 * POLL, game_server(players=0))

    assert world.games.rows[0].is_ongoing is True


def test_brief_listing_dropout_does_not_end_the_game(world):
    world.repeat(timedelta(minutes=10), game_server())
    world.repeat(timedelta(minutes=2))
    world.poll(game_server())

    assert len(world.games.rows) == 1
    assert world.games.rows[0].is_ongoing is True


# ---- servers that leave the listing altogether ----

def test_server_gone_from_the_listing_is_closed_with_its_last_time_seen(world):
    other = game_server(id='B', status='lobby')
    world.repeat(timedelta(minutes=10), game_server(), other)
    gone_at = world.now

    world.poll_past_grace(other)

    game = world.games.rows[0]
    assert game.game_end == gone_at
    assert game.is_valid_game is True
    assert world.tracker.active_sessions == {}


def test_empty_steam_answer_still_runs_the_grace_period(world):
    world.repeat(timedelta(minutes=10), game_server())
    world.poll_past_grace()

    assert world.games.rows[0].is_ongoing is False


# ---- status_known ----

def test_unknown_status_with_people_holds_the_session_through_a_long_outage(world):
    world.repeat(timedelta(minutes=10), game_server())
    # A2S rules are down, so `status` is the fallback 'lobby' guess.
    world.repeat(timedelta(minutes=30), game_server(status='lobby', status_known=False))

    game = world.games.rows[0]
    assert game.is_ongoing is True
    assert game.game_end is None

    world.poll(game_server())
    assert len(world.games.rows) == 1


def test_unknown_status_never_starts_a_session(world):
    world.repeat(timedelta(minutes=5), game_server(status='in_game', status_known=False))

    assert world.games.rows == []


def test_unknown_status_with_no_people_runs_the_grace_period(world):
    world.repeat(timedelta(minutes=10), game_server())
    left_at = world.now

    world.poll_past_grace(game_server(players=0, status='lobby', status_known=False))

    game = world.games.rows[0]
    assert game.game_end == left_at
    assert game.is_ongoing is False


# ---- which games are recorded ----

@pytest.mark.parametrize('hidden', [
    game_server(players=6, bots=2),
    game_server(name='Clan Only Private Server'),
    game_server(players=0),
])
def test_servers_the_display_filter_hides_do_not_start_sessions(world, hidden):
    world.repeat(timedelta(minutes=10), hidden)

    assert world.games.rows == []
    assert world.tracker.active_sessions == {}


def test_tracked_game_is_followed_when_a_bot_joins(world):
    world.repeat(timedelta(minutes=6), game_server())
    world.repeat(timedelta(minutes=4), game_server(players=7, bots=1))
    world.poll(game_server(players=7, bots=1, status='debrief'))

    game = world.games.rows[0]
    assert game.duration_seconds == 600
    assert game.players_at_end == 6
    assert game.max_players_during_game == 6


def test_server_left_with_only_bots_counts_as_empty(world):
    world.repeat(timedelta(minutes=6), game_server())
    left_at = world.now

    world.poll_past_grace(game_server(players=2, bots=2))

    assert world.games.rows[0].game_end == left_at


def test_rename_to_a_private_style_name_does_not_lose_the_game(world):
    world.repeat(timedelta(minutes=6), game_server())
    world.poll(game_server(status='lobby', name='Private Practice'))

    game = world.games.rows[0]
    assert game.duration_seconds == 360
    assert game.is_ongoing is False


# ---- per-poll cost ----

def test_untracked_empty_servers_cost_no_database_work(world):
    empties = [game_server(players=0, id=f'empty-{n}', status=s)
               for n, s in enumerate(['lobby', 'in_game', 'debrief'] * 10)]

    world.repeat(timedelta(minutes=10), *empties)

    assert world.games.queries == 0
    assert world.tracker._unoccupied_since == {}


def test_tracked_empty_server_costs_no_database_work_during_the_grace_period(world):
    world.poll(game_server())
    world.games.queries = 0

    world.repeat(GRACE - POLL, game_server(players=0))

    assert world.games.queries == 0


def test_tracking_state_is_released_when_a_session_closes(world):
    world.repeat(timedelta(minutes=6), game_server(id='A'), game_server(id='B'))
    world.poll_past_grace(game_server(id='A', players=0))

    assert world.tracker.active_sessions == {}
    assert world.tracker._unoccupied_since == {}


# ---- debrief ----

def test_debrief_straight_to_in_game_starts_a_new_row(world):
    world.repeat(timedelta(minutes=10), game_server())
    world.poll(game_server(status='debrief'))
    ended = world.games.rows[0].game_end

    world.repeat(timedelta(minutes=1), game_server(players=8))

    assert len(world.games.rows) == 2
    old, new = world.games.rows
    assert old.game_end == ended
    assert old.max_players_during_game == 4
    assert new.players_at_start == 8
    assert new.is_ongoing is True


def test_server_emptied_in_debrief_keeps_the_recorded_end(world):
    world.repeat(timedelta(minutes=10), game_server())
    world.poll(game_server(status='debrief'))
    ended = world.games.rows[0].game_end

    world.poll_past_grace(game_server(players=0, status='debrief'))

    game = world.games.rows[0]
    assert game.game_end == ended
    assert game.is_valid_game is True
    assert world.tracker.active_sessions == {}


def test_normal_game_lifecycle_is_unchanged(world):
    world.repeat(timedelta(minutes=10), game_server())
    ended = world.now
    world.repeat(timedelta(minutes=1), game_server(status='debrief'))
    world.poll(game_server(status='lobby'))

    game = world.games.rows[0]
    assert game.game_end == ended
    assert game.duration_seconds == 600
    assert game.is_valid_game is True
    assert world.tracker.active_sessions == {}


# ---- recovery after a restart ----

def recover(world, *servers_ids):
    for server_id in servers_ids:
        world.games.create(
            server_id=server_id, server_name='Public', server_address='a:1', map_name='Arroyo',
            game_start=world.now - timedelta(hours=2), is_ongoing=True,
        )
    world.tracker._recovery_pending = True


def test_recovered_game_never_seen_with_people_closes_invalid(world):
    recover(world, 'A')

    world.poll_past_grace(game_server(players=0))

    game = world.games.rows[0]
    assert game.is_ongoing is False
    assert game.is_valid_game is False
    assert game.game_end is None
    assert world.tracker.active_sessions == {}
    assert world.tracker._unconfirmed == set()


def test_recovered_game_on_a_vanished_server_closes_invalid(world):
    recover(world, 'A')

    world.poll_past_grace(game_server(id='B', status='lobby'))

    assert world.games.rows[0].is_ongoing is False
    assert world.games.rows[0].is_valid_game is False


def test_recovered_game_on_an_empty_lobby_does_not_invent_a_duration(world):
    recover(world, 'A')

    world.poll(game_server(players=0, status='lobby'))
    assert world.games.rows[0].game_end is None

    world.poll_past_grace(game_server(players=0, status='lobby'))
    assert world.games.rows[0].is_valid_game is False
    assert world.games.rows[0].game_end is None


def test_recovered_game_with_people_keeps_going_and_ends_normally(world):
    recover(world, 'A')

    world.repeat(timedelta(minutes=2), game_server())
    left_at = world.now
    world.poll_past_grace(game_server(players=0))

    game = world.games.rows[0]
    assert world.tracker._unconfirmed == set()
    assert game.game_end == left_at
    assert game.is_valid_game is True

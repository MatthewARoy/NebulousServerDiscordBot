"""Tests for deferred ongoing-game recovery (review item #28).

Constructing GameSessionTracker must not touch the DB (it happens inside
async on_ready, where the ORM raises SynchronousOnlyOperation); recovery
runs exactly once, on the first sync-context update.
"""
from nebulous_bot.statistics_tracker import GameSessionTracker


def test_init_does_not_hit_the_database():
    # CI runs no migrations, so any DB access here would blow up.
    tracker = GameSessionTracker()
    assert tracker._recovery_pending is True
    assert tracker.active_sessions == {}


def test_ensure_recovered_runs_exactly_once(monkeypatch):
    tracker = GameSessionTracker()
    calls = []
    monkeypatch.setattr(tracker, '_recover_ongoing_games', lambda: calls.append(1))

    tracker.ensure_recovered()
    tracker.ensure_recovered()

    assert calls == [1]
    assert tracker._recovery_pending is False

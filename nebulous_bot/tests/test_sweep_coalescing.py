"""Tests for command-triggered sweep suppression and coalescing.

Before this, every !listservers / !openlobbies / !nextgame ran a full
force_update() — a Steam HTTP call plus an A2S query to every server —
inline, before replying. Ten users in one 30 s window meant ten full sweeps
competing for the same six-worker thread pool on the production VM, while
the monitoring loop was refreshing the very same data every 30 s anyway.

Commands now read the cache and only sweep when the monitoring loop has
fallen behind. Pure-logic: ServerMonitor is built with __new__ and given
just the attributes these paths touch (project convention — no DB, no
network).
"""
import asyncio
from datetime import datetime, timedelta, timezone

from nebulous_bot.config import Config
from nebulous_bot.server_monitor import ServerMonitor


def make_monitor(age_seconds=None):
    """A monitor whose cache is `age_seconds` old (None = never updated)."""
    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.cached_servers = []
    monitor.cached_all_servers = []
    monitor.sweeps = 0
    if age_seconds is None:
        monitor.last_update = None
    else:
        monitor.last_update = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)

    async def fake_update_server_list():
        monitor.sweeps += 1
        # A real sweep is slow; make that visible so the coalescing test
        # actually has a window in which callers can pile up.
        await asyncio.sleep(0.05)
        monitor.last_update = datetime.now(timezone.utc)

    monitor._update_server_list = fake_update_server_list
    return monitor


def test_fresh_cache_means_no_sweep():
    monitor = make_monitor(age_seconds=5)
    assert asyncio.run(monitor.ensure_fresh()) is False
    assert monitor.sweeps == 0


def test_stale_cache_triggers_a_sweep():
    monitor = make_monitor(age_seconds=Config.SERVER_CACHE_MAX_AGE + 10)
    assert asyncio.run(monitor.ensure_fresh()) is True
    assert monitor.sweeps == 1


def test_never_updated_cache_triggers_a_sweep():
    # last_update is None on a monitor that has not completed its first loop.
    monitor = make_monitor(age_seconds=None)
    assert monitor.cache_age_seconds() == float('inf')
    assert asyncio.run(monitor.ensure_fresh()) is True
    assert monitor.sweeps == 1


def test_concurrent_commands_collapse_into_one_sweep():
    # The regression this guards: ten users running !ls at once used to mean
    # ten sweeps. They must now produce exactly one.
    monitor = make_monitor(age_seconds=Config.SERVER_CACHE_MAX_AGE + 10)

    async def ten_at_once():
        return await asyncio.gather(*(monitor.ensure_fresh() for _ in range(10)))

    results = asyncio.run(ten_at_once())
    assert monitor.sweeps == 1
    # Exactly one caller did the work; the rest got the fresh result free.
    assert sum(1 for r in results if r) == 1


def test_concurrent_force_updates_also_collapse():
    # !refresh keeps force semantics, but spamming it must not stack sweeps.
    monitor = make_monitor(age_seconds=600)

    async def fake_status_message():
        return None

    monitor._update_status_message = fake_status_message

    async def five_at_once():
        await asyncio.gather(*(monitor.force_update() for _ in range(5)))

    asyncio.run(five_at_once())
    assert monitor.sweeps == 1


def test_force_update_still_sweeps_a_cache_the_commands_would_accept():
    # A cache younger than SERVER_CACHE_MAX_AGE satisfies ensure_fresh but
    # must NOT satisfy an explicit !refresh — that command means "go look".
    monitor = make_monitor(age_seconds=20)

    async def fake_status_message():
        return None

    monitor._update_status_message = fake_status_message

    assert asyncio.run(monitor.ensure_fresh()) is False
    assert monitor.sweeps == 0

    asyncio.run(monitor.force_update())
    assert monitor.sweeps == 1

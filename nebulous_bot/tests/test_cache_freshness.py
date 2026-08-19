"""Pure-logic tests for command-path cache freshness (no DB, no network).

`!listservers`, `!openlobbies` and `!nextgame` used to await force_update(),
which made every invocation wait out a full Steam + A2S sweep (~10 s in
production). They now call ensure_fresh_cache(), which sweeps only when the
monitoring loop's cache is cold or stale. ServerMonitor is built via __new__
per house pattern, with just the attributes these paths touch.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from nebulous_bot.config import Config
from nebulous_bot.server_monitor import ServerMonitor


def _monitor(age_seconds=None, servers=1):
    """A monitor whose cache is `age_seconds` old, with force_update spied."""
    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.cached_servers = [{'name': 'srv'} for _ in range(servers)]
    monitor.last_update = (
        None if age_seconds is None
        else datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    )
    monitor._refresh_lock = asyncio.Lock()
    monitor.sweeps = []

    async def fake_force_update():
        monitor.sweeps.append(True)
        monitor.cached_servers = [{'name': 'srv'}]
        monitor.last_update = datetime.now(timezone.utc)

    monitor.force_update = fake_force_update
    return monitor


# --- cache_age_seconds --------------------------------------------------

def test_cache_age_is_none_before_the_first_sweep():
    assert _monitor(age_seconds=None).cache_age_seconds() is None


def test_cache_age_is_none_when_the_cache_is_empty():
    assert _monitor(age_seconds=5, servers=0).cache_age_seconds() is None


def test_cache_age_measures_from_the_last_sweep():
    assert 39 <= _monitor(age_seconds=40).cache_age_seconds() <= 41


# --- ensure_fresh_cache -------------------------------------------------

def test_fresh_cache_is_served_without_a_sweep():
    monitor = _monitor(age_seconds=20)
    age = asyncio.run(monitor.ensure_fresh_cache())
    assert monitor.sweeps == []
    assert 19 <= age <= 21


def test_a_full_loop_period_still_counts_as_fresh():
    # UPDATE_INTERVAL plus a worst-case sweep is ~45 s; that must not make
    # every command pay for a live refresh.
    monitor = _monitor(age_seconds=Config.UPDATE_INTERVAL + 15)
    asyncio.run(monitor.ensure_fresh_cache())
    assert monitor.sweeps == []


def test_stale_cache_triggers_one_sweep():
    monitor = _monitor(age_seconds=Config.COMMAND_CACHE_MAX_AGE + 30)
    age = asyncio.run(monitor.ensure_fresh_cache())
    assert monitor.sweeps == [True]
    assert age < 1


def test_cold_cache_triggers_a_sweep():
    monitor = _monitor(age_seconds=None)
    asyncio.run(monitor.ensure_fresh_cache())
    assert monitor.sweeps == [True]


def test_empty_cache_triggers_a_sweep_even_if_recently_stamped():
    monitor = _monitor(age_seconds=1, servers=0)
    asyncio.run(monitor.ensure_fresh_cache())
    assert monitor.sweeps == [True]


def test_concurrent_commands_share_a_single_sweep():
    # Without the lock, a stale cache means one Steam + A2S sweep per
    # command, exactly when the box is already struggling.
    monitor = _monitor(age_seconds=None)

    async def race():
        await asyncio.gather(*(monitor.ensure_fresh_cache() for _ in range(5)))

    asyncio.run(race())
    assert monitor.sweeps == [True]


def test_explicit_max_age_overrides_the_default():
    monitor = _monitor(age_seconds=20)
    asyncio.run(monitor.ensure_fresh_cache(max_age_seconds=5))
    assert monitor.sweeps == [True]

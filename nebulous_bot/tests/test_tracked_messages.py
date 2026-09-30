import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from nebulous_bot.server_monitor import ServerMonitor


def _monitor():
    monitor = ServerMonitor.__new__(ServerMonitor)
    monitor.tracked_messages = {}
    monitor.max_tracked_messages = 3
    return monitor


def test_track_message_refetches_a_durable_channel_message():
    durable = SimpleNamespace(id=17, channel=SimpleNamespace(id=23))
    channel = SimpleNamespace(id=23, fetch_message=AsyncMock(return_value=durable))
    interaction_response = SimpleNamespace(id=17, channel=channel)
    monitor = _monitor()

    assert asyncio.run(monitor.track_message(interaction_response, {"mode": "all"})) is True

    channel.fetch_message.assert_awaited_once_with(17)
    entry = monitor.tracked_messages[23][0]
    assert entry["message"] is durable
    assert entry["metadata"] == {"mode": "all"}


def test_track_message_fails_closed_when_refetch_fails():
    channel = SimpleNamespace(
        id=23,
        fetch_message=AsyncMock(side_effect=AttributeError("message unavailable")),
    )
    interaction_response = SimpleNamespace(id=17, channel=channel)
    monitor = _monitor()

    assert asyncio.run(monitor.track_message(interaction_response)) is False
    assert monitor.tracked_messages == {}

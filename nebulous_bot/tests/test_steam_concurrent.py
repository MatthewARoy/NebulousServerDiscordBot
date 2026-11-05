"""Steam's whole-game player count: parsing, failure handling and /graph."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from nebulous_bot.graph_generator import GraphGenerator
from nebulous_bot.steam_api import SteamAPI


@pytest.mark.parametrize('payload, expected', [
    ({'response': {'player_count': 47, 'result': 1}}, 47),
    ({'response': {'player_count': 0, 'result': 1}}, 0),
    ({'response': {'result': 42}}, None),
    ({'response': {'player_count': 47, 'result': 42}}, None),
    ({'response': {'player_count': '47', 'result': 1}}, None),
    ({'response': {'player_count': True, 'result': 1}}, None),
    ({'response': {'player_count': -1, 'result': 1}}, None),
    ({'response': {}}, None),
    ({}, None),
    (None, None),
])
def test_parse_concurrent_players(payload, expected):
    assert SteamAPI.parse_concurrent_players(payload) == expected


class FakeResponse:
    def __init__(self, status=200, payload=None, error=None):
        self.status = status
        self.payload = payload
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self.payload


def fetch_with(response):
    api = SteamAPI()
    api.session = SimpleNamespace(closed=False, get=lambda *a, **k: response)
    return asyncio.run(api.get_concurrent_players())


def test_get_concurrent_players_returns_the_count():
    assert fetch_with(FakeResponse(payload={'response': {'player_count': 47, 'result': 1}})) == 47


def test_get_concurrent_players_treats_http_errors_as_unknown():
    assert fetch_with(FakeResponse(status=503)) is None


@pytest.mark.parametrize('error', [asyncio.TimeoutError(), OSError('down'), ValueError('bad json')])
def test_get_concurrent_players_treats_exceptions_as_unknown(error):
    assert fetch_with(FakeResponse(error=error)) is None


@pytest.mark.parametrize('text', ['steam', 'steam players', 'players on steam', 'everyone', 'whole game'])
def test_graph_parses_steam_phrases(text):
    assert GraphGenerator.parse_graph_type(text)[0] == 'steam_concurrent'


@pytest.mark.parametrize('text, field', [
    ('players online', 'total_players'),
    ('players', 'total_players'),
    ('servers', 'total_servers'),
    ('lobbies', 'open_lobbies'),
    ('games in progress', 'games_in_progress'),
    ('', 'total_players'),
])
def test_graph_keeps_existing_phrases(text, field):
    assert GraphGenerator.parse_graph_type(text)[0] == field


def test_extract_points_skips_rows_with_no_steam_count():
    first = datetime(2026, 11, 1, tzinfo=timezone.utc)
    second = datetime(2026, 11, 2, tzinfo=timezone.utc)
    third = datetime(2026, 11, 3, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(timestamp=first, steam_concurrent=None, total_players=3),
        SimpleNamespace(timestamp=second, steam_concurrent=0, total_players=4),
        SimpleNamespace(timestamp=third, steam_concurrent=47, total_players=5),
    ]

    assert GraphGenerator.extract_points(rows, 'steam_concurrent') == [(second, 0.0), (third, 47.0)]
    assert len(GraphGenerator.extract_points(rows, 'total_players')) == 3

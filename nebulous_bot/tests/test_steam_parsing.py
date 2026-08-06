"""Tests for SteamAPI server parsing and the default display filter.

Guards the single-sweep refactor: the monitor now fetches ALL servers once
and derives the default view with passes_default_filter, so the enhanced
dicts must preserve the raw fields (bots, players, name) that filter needs.
Pure functions only — no Django, network, or Steam key needed.
"""
from nebulous_bot.config import Config
from nebulous_bot.steam_api import SteamAPI


api = SteamAPI()


def raw(name='Some Server', players=4, bots=0, **extra):
    data = {'name': name, 'players': players, 'bots': bots,
            'addr': '1.2.3.4:27015', 'steamid': 'id-' + name, 'map': 'Arroyo (8P)'}
    data.update(extra)
    return data


def enhance(server_data, rules=None, live_player_count=None, consecutive_a2s_misses=0):
    return api._create_enhanced_server_data(
        server_data, server_data['name'], server_data['players'], rules,
        live_player_count=live_player_count,
        consecutive_a2s_misses=consecutive_a2s_misses,
    )


def test_enhanced_data_preserves_bot_count():
    assert enhance(raw(bots=3))['bots'] == 3
    assert enhance(raw(bots=0))['bots'] == 0


def test_default_filter_hides_empty_bot_and_private_servers():
    assert api.passes_default_filter(enhance(raw())) is True
    assert api.passes_default_filter(enhance(raw(players=0))) is False
    assert api.passes_default_filter(enhance(raw(bots=2))) is False
    assert api.passes_default_filter(enhance(raw(name='Clan Only Private Server'))) is False


def test_rules_inprogress_maps_to_status():
    assert enhance(raw(), {'inprogress': '0'})['status'] == 'lobby'
    assert enhance(raw(), {'inprogress': '1'})['status'] == 'in_game'
    assert enhance(raw(), {'inprogress': '2'})['status'] == 'debrief'
    assert enhance(raw(), None)['status'] == 'lobby'  # no rules -> default


def test_rules_map_overrides_steam_map_and_capacity():
    server = enhance(raw(), {'map': 'Salar (10P)'})
    assert server['map'] == 'Salar (10P)'
    assert server['map_capacity'] == 10


def test_modded_flag_requires_nonempty_modlist():
    assert enhance(raw(), {'modList': 'SomeMod'})['is_modded'] is True
    assert enhance(raw(), {'modlist': ' '})['is_modded'] is False
    assert enhance(raw(), {'modFriendly': '1'})['is_modded'] is False


def test_rules_json_survives_apostrophes():
    # A payload containing an apostrophe must not be corrupted by parsing.
    parsed = api._parse_nebulous_rules_json('{"map": "Pilot\'s Run", "inprogress": "1"}')
    assert parsed.get('map') == "Pilot's Run"
    assert parsed.get('inprogress') == '1'


# --- Live player counts (A2S) supersede Steam's last-heartbeat number -------
# Steam's GetServerList `players` drifts in both directions and stays wrong
# for minutes; measured 2026-08-06, one ERI server sat at Steam=4 while 8
# players were connected for ~7 minutes straight, another held Steam=5 while
# emptying to 1. A2S_PLAYER is the real count.

LIVE_RULES = {'inprogress': '0'}  # any rules response proves the server answered


def test_live_count_supersedes_stale_steam_count():
    # Steam over-reporting (the "shows 6/8, nobody there" complaint).
    server = enhance(raw(players=6), LIVE_RULES, live_player_count=0)
    assert server['players'] == 0
    assert server['player_count_source'] == 'a2s'

    # ...and under-reporting, which hid real players from !ls and !nextgame.
    assert enhance(raw(players=4), live_player_count=8)['players'] == 8


def test_uncorroborated_zero_is_not_believed():
    # Count arrived but rules didn't: the server only half-answered, which is
    # not enough to drop it out of the filtered cache. Dropping it would also
    # drop its game-start tracking entry and lose the in_game -> debrief
    # transition that fires !nextgame notifications.
    server = enhance(raw(players=6), None, live_player_count=0)
    assert server['players'] == 6
    assert server['player_count_source'] == 'steam'

    # A zero WITH rules is a real empty server and is believed (above).
    # A nonzero count needs no corroboration — it can only add a server.
    assert enhance(raw(players=0), None, live_player_count=3)['players'] == 3


def test_steam_count_kept_when_a2s_does_not_answer():
    # A dropped UDP packet must not flicker a populated server off the list.
    server = enhance(raw(players=5), live_player_count=None)
    assert server['players'] == 5
    assert server['player_count_source'] == 'steam'
    assert api.passes_default_filter(server) is True


def test_empty_server_with_stale_steam_count_is_filtered_out():
    # The end-to-end effect: an empty server Steam still claims is populated
    # drops out of the default view instead of being advertised as joinable.
    server = enhance(raw(players=6), LIVE_RULES, live_player_count=0)
    assert api.passes_default_filter(server) is False


# --- Lifecycle vs display filtering ----------------------------------------
# Accurate counts made empty servers vanish from the filtered cache, and that
# cache is what _track_game_start_times watches. A match ending means debrief
# AND (usually) zero players in the same cycle, so filtering empties out of
# tracking loses the transition that fires !nextgame and closes GameSessions.

def test_empty_server_stays_in_the_lifecycle_set():
    empty_debrief = enhance(raw(players=8), {'inprogress': '2'}, live_player_count=0)
    assert empty_debrief['status'] == 'debrief'
    # Hidden from users...
    assert api.passes_default_filter(empty_debrief) is False
    # ...but still tracked, so the debrief transition is observed.
    assert api.passes_lifecycle_filter(empty_debrief) is True


def test_lifecycle_set_still_excludes_bot_and_private_servers():
    assert api.passes_lifecycle_filter(enhance(raw(bots=2))) is False
    assert api.passes_lifecycle_filter(enhance(raw(name='Private Clan Server'))) is False


# --- Servers that have stopped answering entirely ---------------------------

def test_server_is_hidden_once_a2s_has_been_silent_long_enough():
    threshold = Config.A2S_UNREACHABLE_THRESHOLD

    # Ordinary packet loss changes nothing: Steam's count is kept and the
    # server stays visible.
    flaky = enhance(raw(players=6), consecutive_a2s_misses=threshold - 1)
    assert flaky['is_unreachable'] is False
    assert api.passes_default_filter(flaky) is True

    # Sustained silence means the Steam entry is a ghost: a dead server must
    # not keep rendering as a joinable lobby or triggering !nextgame.
    dead = enhance(raw(players=6), consecutive_a2s_misses=threshold)
    assert dead['is_unreachable'] is True
    assert api.passes_default_filter(dead) is False
    assert api.passes_lifecycle_filter(dead) is False


def test_a2s_outcome_tracking_resets_on_a_successful_answer():
    tracker = SteamAPI()
    assert tracker._record_a2s_outcome('1.2.3.4:27015', answered=False) == 1
    assert tracker._record_a2s_outcome('1.2.3.4:27015', answered=False) == 2
    # One good answer clears the streak.
    assert tracker._record_a2s_outcome('1.2.3.4:27015', answered=True) == 0
    assert tracker._record_a2s_outcome('1.2.3.4:27015', answered=False) == 1
    # Counts are per-server.
    assert tracker._record_a2s_outcome('5.6.7.8:27015', answered=False) == 1


def test_extract_live_player_count_variants():
    assert api._extract_live_player_count({'player_count': 7}) == 7
    assert api._extract_live_player_count({'player_count': 0}) == 0
    # Header count missing -> fall back to the length of the player list.
    assert api._extract_live_player_count({'players': [{}, {}, {}]}) == 3
    # Nothing usable -> None, so the Steam value is kept.
    assert api._extract_live_player_count({}) is None
    assert api._extract_live_player_count(None) is None
    assert api._extract_live_player_count({'player_count': 'n/a'}) is None
    assert api._extract_live_player_count({'player_count': -1}) is None

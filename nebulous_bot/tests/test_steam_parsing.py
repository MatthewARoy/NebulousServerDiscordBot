"""Tests for SteamAPI server parsing and the default display filter.

Guards the single-sweep refactor: the monitor now fetches ALL servers once
and derives the default view with passes_default_filter, so the enhanced
dicts must preserve the raw fields (bots, players, name) that filter needs.
Also guards the live A2S_INFO enrichment: the Steam listing lags by minutes
(the ERI 5 wrong-map/wrong-population bug), so live info must override it.
Pure functions only — no Django, network, or Steam key needed.
"""
import struct

from nebulous_bot.steam_api import SteamAPI


api = SteamAPI()


def raw(name='Some Server', players=4, bots=0, **extra):
    data = {'name': name, 'players': players, 'bots': bots,
            'addr': '1.2.3.4:27015', 'steamid': 'id-' + name, 'map': 'Arroyo (8P)'}
    data.update(extra)
    return data


def enhance(server_data, rules=None, info=None):
    return api._create_enhanced_server_data(
        server_data, server_data['name'], server_data['players'], rules, info
    )


def info_packet(name='[ERI #5] Lesten', map_name='Gold Rush (8P)',
                players=9, max_players=16, bots=0):
    """Build a valid A2S_INFO response packet (Source format)."""
    return (
        b"\xFF\xFF\xFF\xFFI" + bytes([0x11])
        + name.encode() + b"\x00"
        + map_name.encode() + b"\x00"
        + b"nebulous\x00"
        + b"NEBULOUS: Fleet Command\x00"
        + struct.pack("<H", 0)
        + bytes([players, max_players, bots])
        + b"\x00" * 4  # trailing fields the parser ignores
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


def test_parse_a2s_info_response_golden_packet():
    parsed = SteamAPI.parse_a2s_info_response(info_packet())
    assert parsed == {
        'name': '[ERI #5] Lesten',
        'map': 'Gold Rush (8P)',
        'players': 9,
        'max_players': 16,
        'bots': 0,
    }


def test_parse_a2s_info_response_rejects_bad_packets():
    # Challenge packet ('A' response type) is not an info response
    assert SteamAPI.parse_a2s_info_response(b"\xFF\xFF\xFF\xFFA\x01\x02\x03\x04") is None
    # Truncated / garbage / empty packets must not raise
    assert SteamAPI.parse_a2s_info_response(b"") is None
    assert SteamAPI.parse_a2s_info_response(b"\xFF\xFF\xFF\xFFI\x11no terminators") is None
    assert SteamAPI.parse_a2s_info_response(b"garbage-not-a2s") is None


def test_live_info_overrides_stale_steam_listing():
    # The ERI 5 bug: listing said Nyx's Eye (10P) with 8 players while the
    # server was live on Gold Rush (8P) with 9. Live info must win.
    steam = raw(players=8, map="Nyx's Eye (10P)")
    info = SteamAPI.parse_a2s_info_response(info_packet())
    server = enhance(steam, rules={'inprogress': '0'}, info=info)
    assert server['map'] == 'Gold Rush (8P)'
    assert server['map_capacity'] == 8
    assert server['players'] == 9
    assert server['max_players'] == 16


def test_legacy_rules_map_beats_info_map():
    # If a server build ever publishes 'map' in rules again, it stays the
    # most authoritative source.
    info = SteamAPI.parse_a2s_info_response(info_packet(map_name='Pillars (8P)'))
    server = enhance(raw(), rules={'map': 'Salar (10P)'}, info=info)
    assert server['map'] == 'Salar (10P)'
    assert server['map_capacity'] == 10


def test_no_info_falls_back_to_steam_listing():
    server = enhance(raw(players=5), rules=None, info=None)
    assert server['map'] == 'Arroyo (8P)'
    assert server['players'] == 5


def test_default_filter_uses_live_player_count():
    # Listing claims players but the server is live-empty: hide it.
    ghost = enhance(raw(players=3), info=SteamAPI.parse_a2s_info_response(
        info_packet(players=0)))
    assert api.passes_default_filter(ghost) is False
    # Listing says empty but players actually joined: show it.
    busy = enhance(raw(players=0), info=SteamAPI.parse_a2s_info_response(
        info_packet(players=4)))
    assert api.passes_default_filter(busy) is True


def test_live_info_overrides_bot_count():
    with_bots = enhance(raw(bots=0), info=SteamAPI.parse_a2s_info_response(
        info_packet(bots=2)))
    assert with_bots['bots'] == 2
    assert api.passes_default_filter(with_bots) is False

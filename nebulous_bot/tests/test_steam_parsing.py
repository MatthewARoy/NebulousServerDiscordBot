"""Tests for SteamAPI server parsing and the default display filter.

Guards the single-sweep refactor: the monitor now fetches ALL servers once
and derives the default view with passes_default_filter, so the enhanced
dicts must preserve the raw fields (bots, players, name) that filter needs.
Pure functions only — no Django, network, or Steam key needed.
"""
from nebulous_bot.steam_api import SteamAPI


api = SteamAPI()


def raw(name='Some Server', players=4, bots=0, **extra):
    data = {'name': name, 'players': players, 'bots': bots,
            'addr': '1.2.3.4:27015', 'steamid': 'id-' + name, 'map': 'Arroyo (8P)'}
    data.update(extra)
    return data


def enhance(server_data, rules=None):
    return api._create_enhanced_server_data(
        server_data, server_data['name'], server_data['players'], rules
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

"""Modded-server detection tests for SteamAPI.

A server counts as 'modded' when its rules advertise a non-empty modList
(the actual list of loaded mods). Verified against live MFC (modded) and
ERI (vanilla) servers.
"""
from nebulous_bot.steam_api import SteamAPI

api = SteamAPI()


def test_modded_when_modlist_present():
    assert api._rules_indicate_modded({'modList': 'Damen Shipyards Group, Praetorian Cruiser'}) is True


def test_modded_lowercased_key():
    # The direct-rules path lowercases keys.
    assert api._rules_indicate_modded({'modlist': 'Aegir Fleet'}) is True


def test_not_modded_when_modlist_absent_or_empty():
    assert api._rules_indicate_modded({'modFriendly': '0'}) is False
    assert api._rules_indicate_modded({'modList': ''}) is False
    assert api._rules_indicate_modded({'modList': '   '}) is False
    assert api._rules_indicate_modded({}) is False
    assert api._rules_indicate_modded(None) is False


def test_enhanced_server_data_sets_is_modded():
    modded = api._create_enhanced_server_data(
        {'addr': '1.2.3.4', 'name': '[MFC #1] - Arena'}, '[MFC #1] - Arena', 6,
        {'inprogress': '0', 'modList': 'Damen Shipyards Group'},
    )
    vanilla = api._create_enhanced_server_data(
        {'addr': '1.2.3.4', 'name': '[ERI #6] Miramare'}, '[ERI #6] Miramare', 6,
        {'inprogress': '0', 'modFriendly': '0'},
    )
    no_rules = api._create_enhanced_server_data(
        {'addr': '1.2.3.4', 'name': 'Some Server'}, 'Some Server', 6, None,
    )
    assert modded['is_modded'] is True
    assert vanilla['is_modded'] is False
    assert no_rules['is_modded'] is False

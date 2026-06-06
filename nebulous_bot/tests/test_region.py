"""Region-detection tests for SteamAPI.

Regression coverage for the bug where the official ERI servers moved to new
IP ranges (51.81.x / 15.204.x) after a Nebulous patch, fell through the
hardcoded IP table, and displayed "Region: Unknown". Region is now parsed
from the server name as a fallback when the IP doesn't resolve.

These exercise pure functions only — no Django, network, or Steam key needed.
"""
from nebulous_bot.steam_api import SteamAPI


api = SteamAPI()


def test_known_ip_ranges_resolve():
    assert api._determine_region('23.132.156.68') == 'US'
    assert api._determine_region('87.106.119.156') == 'EU'
    assert api._determine_region('51.161.140.10') == 'AU'
    assert api._determine_region('116.230.1.1') == 'AS'


def test_eri_servers_on_new_ips_resolve_via_name():
    # The exact regression: new OVH IPs miss the IP table, name carries region.
    assert api._determine_region('51.81.33.228', '[ERI #6] Miramare - Casual Play (US EAST)') == 'US'
    assert api._determine_region('15.204.116.134', '[ERI #5] Lesten - Casual Play (US WEST)') == 'US'
    assert api._determine_region('15.204.93.154', '[ERI #7] Kribensis - Competitive/Stack Play (US WEST)') == 'US'


def test_name_fallback_for_other_regions():
    assert api._determine_region('1.2.3.4', '[EU] Bizarre Adventure #1') == 'EU'
    assert api._determine_region('1.2.3.4', '【JPN】ちきんサーバー 本館') == 'AS'
    assert api._determine_region('1.2.3.4', '[CN]Beijing Aliyun ECS') == 'AS'


def test_ip_takes_precedence_over_name():
    # A resolvable IP wins; name parsing only runs as a fallback.
    assert api._determine_region('23.132.156.68', 'some [EU] vanity tag') == 'US'


def test_unresolvable_stays_unknown():
    assert api._determine_region('', '') == 'Unknown'
    assert api._determine_region('8.8.8.8', 'AMP Powered NEBULOUS: Fleet Command Server') == 'Unknown'

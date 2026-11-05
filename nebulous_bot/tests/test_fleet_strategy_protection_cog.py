"""Regional protection rendering preserves limited coverage and actionable candidates."""

import copy
from unittest.mock import patch

import pytest

from nebulous_bot.cogs.fleet_strategy import FleetStrategyCog, _arguments, _review_embed
from nebulous_bot.tests.test_fleet_strategy_cog import Attachment, Context, cog, invoke


PROTECTION = {
    'status': 'assessed', 'build_id': 'build-fixture', 'geometry_id': 'geometry-fixture',
    'evidence_scope': 'geometry-sampled; entry/effect origin assumed', 'provenance': ['Fixture collider source.'],
    'threat_id': 'hei', 'direction': 'bow', 'summary': 'Sparse hypothetical internal paths only.',
    'limitations': ['Armor penetration and other paths are untested.'],
    'ships': [{
        'ship_key': 'ShipCase', 'ship_name': 'Example ship', 'status': 'assessed',
        'summary': 'One critical component exceeds DT; another is within sampled DT.',
        'parts': [
            {'socket_key': 'CIC', 'component': 'Basic CIC', 'region': 'bow', 'status': 'threshold-exceeded',
             'worst_packet': 50, 'threshold': 40, 'margin': -10, 'tested_paths': 5, 'unknown_paths': 0,
             'supporting_sockets': ['Locker'], 'support_status': 'vulnerable', 'reason': 'Limiting path has one recipient.',
             'paths': [{'index': 2, 'status': 'threshold-exceeded', 'packet': 50, 'margin': -10,
                        'geometry': {'length': 7}, 'recipients': ['CIC']}]},
            {'socket_key': 'Locker', 'component': 'Reinforced DC Locker', 'region': 'bow', 'status': 'within-dt',
             'worst_packet': 20, 'threshold': 35, 'margin': 15, 'tested_paths': 5, 'unknown_paths': 0,
             'supporting_sockets': ['CIC'], 'support_status': 'within-dt', 'reason': 'Packets stay within DT on sampled paths.'},
        ],
        'suggestions': [{
            'summary': 'Consider reinforced support; check the change in game.', 'socket_key': 'Support',
            'component': 'Reinforced DC Locker', 'previous_component': 'Damage Control Locker',
            'target_sockets': ['CIC'], 'before_margin': -10, 'after_margin': 15,
            'limitations': ['Confirm legality, cost, displaced function and power in game.'],
        }],
    }],
}


def test_automatic_threat_and_direction_options_do_not_require_manual_stack():
    role, investment, scenario, protection = _arguments('frontline --threat 450-he --direction PORT', calculator=True)
    assert (role, investment, scenario) == ('frontline', 'standard', None)
    assert protection == {'threat_id': '450-he', 'direction': 'port'}


@pytest.mark.parametrize('options', ['--direction diagonal', '--direction', '--direction bow --direction port',
                                     '--stack Ship:A --threat hei --dr 0.2 --direction port'])
def test_invalid_automatic_options_fail_before_attachment_download(options):
    attachment = Attachment()
    ctx = Context([attachment])
    invoke(cog(), ctx, role=options)
    assert attachment.read_count == 0
    assert 'document' not in ctx.sent[-1]


def test_automatic_request_passes_configured_geometry_and_options():
    instance = cog()
    instance.geometry = {'geometry_id': 'fixture'}
    ctx = Context([Attachment()])
    with patch('nebulous_bot.cogs.fleet_strategy.review_fleet', return_value={'protection': copy.deepcopy(PROTECTION)}) as review:
        invoke(instance, ctx, role='--threat 450-he --direction stern')
    assert review.call_args.kwargs['geometry'] is instance.geometry
    assert review.call_args.kwargs['protection_threat'] == '450-he'
    assert review.call_args.kwargs['protection_direction'] == 'stern'
    report = ctx.sent[-1]['document']
    for value in ('Regional component protection:', 'build-fixture', 'geometry-fixture',
                  'Worst sampled packet: 50', 'margin: -10', 'Supporting sockets: Locker',
                  'Tested paths: 5', 'unknown paths: 0', 'Candidate change:',
                  'Target sockets: CIC', 'margin before: -10; after: 15',
                  'displaced function', 'Armor penetration', 'does not certify an immune region',
                  'Supporting-part DT status: vulnerable', 'Probe 2: threshold-exceeded',
                  'Recipients: CIC', 'entry/effect origin assumed', 'Fixture collider source.', 'Damage-model evidence:'):
        assert value in report


def test_unknown_coverage_stays_grey_and_avoids_reassuring_zero_counts():
    embed = _review_embed({'protection': dict(PROTECTION, status='unknown', ships=[], summary='No matching geometry.')}, None)
    assert embed.color.value == 0x808080
    assert 'Component coverage unavailable' in embed.fields[0].value
    assert '0 within' not in embed.fields[0].value


def test_mixed_results_show_counts_and_candidates_without_immunity_claim():
    embed = _review_embed({'protection': PROTECTION}, None)
    assert embed.color.value == 0xE0A000
    assert '1 within sampled DT' in embed.fields[0].value
    assert '1 target/support breaches' in embed.fields[0].value
    assert 'No combat immunity guarantee' in embed.fields[0].value
    assert 'candidate changes' in embed.fields[1].value


@pytest.mark.parametrize('support,color,counts', [
    ('within-dt', 0x3498DB, '1 within sampled DT with known support'),
    ('vulnerable', 0xE0A000, '1 target/support breaches'),
    ('unknown', 0x808080, '1 unknown target/support components'),
    (None, 0x808080, '1 unknown target/support components'),
])
def test_within_target_does_not_hide_support_risk_in_summary(support, color, counts):
    protection = copy.deepcopy(PROTECTION)
    target = protection['ships'][0]['parts'][1]
    target['support_status'] = support
    protection['ships'][0]['parts'] = [target]
    embed = _review_embed({'protection': protection}, None)
    assert target['status'] == 'within-dt'
    assert embed.color.value == color
    assert counts in embed.fields[0].value
    if support != 'within-dt':
        assert '0 within sampled DT with known support' in embed.fields[0].value


def test_protection_embed_is_bounded_and_mention_safe():
    protection = copy.deepcopy(PROTECTION)
    protection['summary'] = '@everyone *pretend safe* ' * 1000
    protection['ships'] *= 100
    for ship in protection['ships']:
        ship['ship_name'] = '@here' * 1000
        ship['summary'] = '<@123456> ' * 1000
    embed = _review_embed({'protection': protection}, None)
    text = str(embed.to_dict())
    assert len(embed) <= 5000 and len(embed.fields) <= 25
    assert all(len(field.value) <= 1024 and len(field.name) <= 256 for field in embed.fields)
    assert '@everyone' not in text and '@here' not in text and '<@123456>' not in text


def test_missing_moderation_state_retains_independent_protection_checks():
    ctx = Context([Attachment()])
    with patch('nebulous_bot.cogs.fleet_strategy.review_protection', return_value=copy.deepcopy(PROTECTION)) as protection, \
            patch('nebulous_bot.cogs.fleet_strategy.review_fleet') as advice:
        invoke(cog(available=False), ctx, role='--threat hei --direction bow')
    advice.assert_not_called()
    protection.assert_called_once()
    assert 'community removal state' in ctx.sent[-1]['document']
    assert 'Worst sampled packet: 50' in ctx.sent[-1]['document']


def test_bad_configured_geometry_is_safe_and_visible(monkeypatch):
    monkeypatch.setenv('FLEET_GEOMETRY_PATH', 'private/local/file.json')
    with patch('nebulous_bot.cogs.fleet_strategy.load_geometry', side_effect=ValueError('sensitive path')):
        instance = FleetStrategyCog(cog().bot)
    assert instance.geometry is None
    ctx = Context([Attachment()])
    invoke(instance, ctx)
    report = ctx.sent[-1]['document']
    assert 'configured geometry dataset could not be loaded' in report
    assert 'sensitive path' not in report and 'private/local' not in report

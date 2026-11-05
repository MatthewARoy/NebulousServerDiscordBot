"""Command-boundary and presentation checks for explicit component DT scenarios."""

from unittest.mock import patch

import pytest

from fleet_strategy import FleetInputError
from nebulous_bot.cogs.fleet_strategy import _arguments, _review_embed
from nebulous_bot.tests.test_fleet_strategy_cog import Attachment, Context, cog, invoke


OPTIONS = '--stack ShipCase:SocketA,SocketB --threat hei --dr 0.2'
REINFORCED_SHIP = (
    b'<Ship><Key>Ship_Case</Key><Name>Nose fixture</Name><HullType>Stock/Keystone Destroyer</HullType><SocketMap>'
    b'<HullSocket><Key>Socket_A</Key><ComponentName>Stock/Reinforced CIC</ComponentName></HullSocket>'
    b'<HullSocket><Key>Socket_B</Key><ComponentName>Stock/Reinforced DC Locker</ComponentName></HullSocket>'
    b'</SocketMap></Ship>'
)
SCENARIO = {
    'status': 'conditional-below-dt', 'title': 'Conditional packet comparison',
    'summary': 'Each selected recipient is below its individual DT under the supplied assumptions.',
    'recipients': [
        {'socket_key': 'SocketA', 'component': 'Reinforced fixture', 'threshold': 40,
         'packet': 20, 'exceeds_threshold': False},
        {'socket_key': 'SocketB', 'component': 'Reinforced fixture', 'threshold': 30,
         'packet': 20, 'exceeds_threshold': False},
    ],
    'assumptions': ['Both selected recipients lie on the modeled ray.', 'Assumed 20% DR.'],
    'limitations': ['No geometry or surrounding components are inferred.', 'Repeated hits are not modeled.'],
    'evidence': ['Audited fixture: https://example.invalid/audit'],
    'threat': {'id': 'hei', 'label': 'HEI maximum ray', 'distribution': 'divide', 'packet_damage': 50},
    'damage_reduction': 0.2, 'game_version': 'test audit version',
}


def test_parser_preserves_identifiers_and_accepts_options_with_role_and_lean():
    role, investment, scenario, protection = _arguments('FRONTLINE --lean ' + OPTIONS, calculator=True)
    assert (role, investment) == ('frontline', 'lean')
    assert scenario == {'ship_key': 'ShipCase', 'socket_keys': ['SocketA', 'SocketB'],
                        'threat_id': 'hei', 'damage_reduction': 0.2}
    assert protection == {'threat_id': 'hei', 'direction': 'bow'}


@pytest.mark.parametrize('text', [
    '--stack ShipCase:SocketA', '--threat hei --dr 0', '--dr 0',
    OPTIONS + ' --dr 0', OPTIONS + ' --threat hei', OPTIONS + ' --stack ShipCase:SocketA',
    '--lean --lean', OPTIONS.replace('ShipCase:SocketA,SocketB', ':SocketA'),
    OPTIONS.replace('ShipCase:SocketA,SocketB', 'ShipCase:'),
    OPTIONS.replace('ShipCase:SocketA,SocketB', 'ShipCase:SocketA,SocketA'),
    OPTIONS.replace('ShipCase:SocketA,SocketB', 'ShipCase:SocketA,,SocketB'),
    OPTIONS.replace('ShipCase:SocketA,SocketB', 'ShipCase:SocketA:SocketB'),
    OPTIONS.replace('--threat hei', '--threat'), OPTIONS + ' --mystery value',
    OPTIONS.replace('--dr 0.2', '--dr=0.2'),
    *[OPTIONS.replace('--dr 0.2', '--dr ' + value) for value in ('nan', 'inf', '-inf', '-0.1', '0.91', '20%', 'abc')],
])
def test_invalid_scenarios_rejected_before_reading_attachment(text):
    attachment = Attachment()
    ctx = Context([attachment])
    with patch('nebulous_bot.cogs.fleet_strategy.evaluate_stack') as evaluate:
        invoke(cog(), ctx, role=text)
    assert attachment.read_count == 0
    assert 'document' not in ctx.sent[-1]
    evaluate.assert_not_called()


@pytest.mark.parametrize('flag', ['--stack ShipCase:SocketA', '--threat hei', '--dr 0.2'])
def test_shipbuilding_does_not_accept_calculator_flags(flag):
    ctx = Context()
    invoke(cog(), ctx, role=flag, command='shipbuilding')
    assert 'only available with !fleetcheck' in ctx.sent[-1]['content']
    assert 'document' not in ctx.sent[-1]


def test_full_report_contains_scenario_recipients_assumptions_limits_and_evidence():
    ctx = Context([Attachment()])
    with patch('nebulous_bot.cogs.fleet_strategy.evaluate_stack', return_value=dict(SCENARIO)) as evaluate:
        invoke(cog(), ctx, role=OPTIONS)
    assert evaluate.call_args.kwargs == _arguments(OPTIONS, calculator=True)[2]
    report = ctx.sent[-1]['document']
    for value in ('Selected ship key: ShipCase', 'Selected socket keys: SocketA, SocketB',
                  'individual DT: 40', 'individual DT: 30', 'modeled packet: 20',
                  'Source packet damage: 50', 'Assumptions:', 'Limits:', 'Evidence:',
                  'Both selected recipients', 'Repeated hits', 'https://example.invalid/audit',
                  'test audit version', 'not a combat immunity or survival guarantee'):
        assert value in report
    assert 'Conditional: within DT' in ctx.sent[-1]['embed'].fields[0].name


def test_unknown_profile_is_rendered_without_claiming_protection():
    ctx = Context([Attachment()])
    unknown = dict(SCENARIO, status='unknown', summary='Unknown threat profile.', recipients=[],
                   threat={'id': 'custom', 'label': 'custom'})
    with patch('nebulous_bot.cogs.fleet_strategy.evaluate_stack', return_value=unknown):
        invoke(cog(), ctx, role=OPTIONS.replace('--threat hei', '--threat custom'))
    assert 'Unknown threat profile.' in ctx.sent[-1]['document']
    assert 'Selected socket keys: SocketA, SocketB' in ctx.sent[-1]['document']
    assert ctx.sent[-1]['embed'].color.value == 0x808080
    assert 'Unknown' in ctx.sent[-1]['embed'].fields[0].name


def test_core_validation_failure_is_returned_safely():
    ctx = Context([Attachment()])
    with patch('nebulous_bot.cogs.fleet_strategy.evaluate_stack', side_effect=FleetInputError('Bad @everyone key')):
        invoke(cog(), ctx, role=OPTIONS)
    assert 'Unable to review' in ctx.sent[-1]['content']
    assert '@everyone' not in ctx.sent[-1]['content']


def test_missing_moderation_withholds_advice_but_keeps_explicit_mechanics_scenario():
    ctx = Context([Attachment()])
    inventory = [{'ship_key': 'ShipCase', 'ship_name': 'Nose fixture',
                  'sockets': [{'key': 'SocketA', 'component': 'Reinforced fixture', 'threshold': 40}]}]
    with patch('nebulous_bot.cogs.fleet_strategy.evaluate_stack', return_value=dict(SCENARIO)) as evaluate, \
            patch('nebulous_bot.cogs.fleet_strategy.review_fleet') as review, \
            patch('nebulous_bot.cogs.fleet_strategy.damage_inventory', return_value=inventory):
        invoke(cog(available=False), ctx, role=OPTIONS)
    review.assert_not_called()
    evaluate.assert_called_once()
    report = ctx.sent[-1]['document']
    assert 'community removal state could not be checked' in report
    assert 'Check: beam-particle-support' not in report
    assert 'Explicit conditional damage scenario:' in report
    assert 'Socket key: SocketA' in report


@pytest.mark.parametrize('status,color,label', [
    ('conditional-below-dt', 0x3498DB, 'Conditional: within DT'),
    ('threshold-exceeded', 0xE0A000, 'Threshold exceeded'),
    ('unknown', 0x808080, 'Unknown'),
])
def test_status_color_is_labeled_bounded_and_mention_safe(status, color, label):
    result = {'fleet_name': '@everyone' * 200, 'findings': [], 'limitations': ['@here' * 1000] * 20,
              'damage_scenario': dict(SCENARIO, status=status, summary='@everyone <@123456> ' * 1000)}
    embed = _review_embed(result, None)
    assert embed.color.value == color
    assert label in embed.fields[0].name
    assert len(embed) <= 5000
    assert len(embed.fields) <= 25
    assert all(len(field.value) <= 1024 and len(field.name) <= 256 for field in embed.fields)
    assert '@everyone' not in embed.fields[0].value
    assert '<@123456>' not in embed.fields[0].value
    assert 'no combat immunity' in embed.fields[0].value


def test_report_escapes_names_keys_and_model_prose():
    malicious = dict(SCENARIO, summary='@everyone **claim**', assumptions=['@here assumption'],
                     limitations=['<@123456> limit'], evidence=['@everyone evidence'],
                     recipients=[dict(SCENARIO['recipients'][0], socket_key='@everyone', component='@here')])
    ctx = Context([Attachment()])
    with patch('nebulous_bot.cogs.fleet_strategy.evaluate_stack', return_value=malicious):
        invoke(cog(), ctx, role=OPTIONS)
    report = ctx.sent[-1]['document']
    assert '@everyone' not in report and '@here' not in report and '<@123456>' not in report
    assert '**claim**' not in report


def test_plain_review_and_shipbuilding_include_usable_calculator_guide():
    inventory = [{'ship_key': 'ShipCase', 'ship_name': 'Nose fixture',
                  'sockets': [{'key': 'SocketA', 'component': 'Reinforced fixture', 'threshold': 40}]}]
    ctx = Context([Attachment()])
    with patch('nebulous_bot.cogs.fleet_strategy.review_fleet', return_value={'damage_inventory': inventory}):
        invoke(cog(), ctx)
    report = ctx.sent[-1]['document']
    assert 'Ship key: ShipCase' in report and 'Socket key: SocketA' in report
    assert '--stack SHIP_KEY:SOCKET,SOCKET --threat ID --dr FRACTION' in report
    ctx = Context()
    invoke(cog(), ctx, command='shipbuilding')
    report = ctx.sent[-1]['document']
    assert '--stack ship-1:SocketA,SocketB --threat hei --dr 0.2' in report
    assert '0.2 means 20%' in report
    assert 'thresholds are not added together' in report
    assert 'grey means unknown' in report


@pytest.mark.parametrize('threat,color', [('hei', 0x3498DB), ('450-he', 0xE0A000), ('unknown-custom', 0x808080)])
def test_real_bundle_scenario_and_copyable_socket_keys(threat, color):
    ctx = Context([Attachment(data=REINFORCED_SHIP)])
    invoke(cog(), ctx, role=f'--stack Ship_Case:Socket_A,Socket_B --threat {threat} --dr 0.2')
    report = ctx.sent[-1]['document']
    assert ctx.sent[-1]['embed'].color.value == color
    assert 'Ship key: Ship_Case' in report
    assert 'Socket key: Socket_A' in report and 'Socket key: Socket_B' in report
    assert 'Selected socket keys: Socket_A, Socket_B' in report
    assert 'not a combat immunity or survival guarantee' in report
    if threat == 'hei':
        assert 'modeled packet: 20.0' in report
        assert 'Weakest-recipient equal-split budget after DR (not summed DT): 70' in report

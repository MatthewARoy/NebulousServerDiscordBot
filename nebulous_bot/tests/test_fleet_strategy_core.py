"""Input boundaries and absence-evidence behavior of the portable evaluator."""

import copy
from pathlib import Path

import pytest

from fleet_strategy import BundleError, FleetInputError, MAX_FLEET_BYTES, load_bundle, parse_design, parse_fleet, review_fleet
from fleet_strategy.parser import MAX_NAME_LENGTH, MAX_SHIPS

ROOT = Path(__file__).resolve().parents[2]
SHIP = '<Ship><Key>s</Key><Name>Example</Name><HullType>Stock/Keystone Destroyer</HullType><SocketMap>{}</SocketMap></Ship>'
BEAM = '<HullSocket><Key>beam</Key><ComponentName>Stock/Mk600 Beam Cannon</ComponentName></HullSocket>'


@pytest.fixture
def bundle():
    return load_bundle(ROOT / 'knowledge')


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'utf-16-be', 'utf-32', 'utf-32-le'])
def test_unicode_xml_and_dtd_blocking(encoding):
    xml = '<?xml version="1.0" encoding="' + encoding + '"?>' + SHIP.format(BEAM)
    assert parse_design(xml.encode(encoding))['ships'][0]['components'] == ['Stock/Mk600 Beam Cannon']
    hostile = '<?xml version="1.0" encoding="' + encoding + '"?><!DOCTYPE Ship [<!ENTITY x "data">]>' + SHIP.format('')
    with pytest.raises(FleetInputError, match='DTD or entity'):
        parse_design(hostile.encode(encoding))


@pytest.mark.parametrize('data', [b'', b'not xml', b'<Fleet>', b'<Wrong/>', b'<Fleet><Ships/></Fleet>',
                                 b'<Fleet><Ships/><Ships/></Fleet>', b'<Ship><SocketMap/></Ship>',
                                 b'<Ship><HullType>x</HullType></Ship>'])
def test_malformed_or_wrong_shape_is_rejected(data):
    with pytest.raises(FleetInputError):
        parse_design(data)


def test_size_depth_name_and_ship_count_limits():
    with pytest.raises(FleetInputError, match='size limit'):
        parse_design(b' ' * (MAX_FLEET_BYTES + 1))
    with pytest.raises(FleetInputError, match='depth limit'):
        parse_design(('<Fleet>' + '<x>' * 70 + '</x>' * 70 + '</Fleet>').encode())
    with pytest.raises(FleetInputError, match='character limit'):
        parse_design(SHIP.format('').replace('Example', 'a' * (MAX_NAME_LENGTH + 1)).encode())
    with pytest.raises(FleetInputError, match='ship limit'):
        parse_fleet(('<Fleet><Ships>' + SHIP.format('') * (MAX_SHIPS + 1) + '</Ships></Fleet>').encode())


def test_only_positive_fitted_loads_count_and_local_templates_resolve(bundle):
    sockets = BEAM + '''<HullSocket><Key>vls</Key><ComponentName>Stock/VLS-1-23 Launcher</ComponentName>
    <ComponentData><MissileLoad><MagSaveData><MunitionKey>$MODMIS$/SGM-1 Test</MunitionKey><Quantity>2</Quantity></MagSaveData>
    <MagSaveData><MunitionKey>Stock/EA12 Chaff Decoy</MunitionKey><Quantity>3</Quantity></MagSaveData></MissileLoad></ComponentData></HullSocket>
    <HullSocket><Key>mag</Key><ComponentName>Stock/Reinforced Magazine</ComponentName><ComponentData><Load>
    <MagSaveData><MunitionKey>Stock/450mm HE Shell</MunitionKey><Quantity>0</Quantity></MagSaveData></Load></ComponentData></HullSocket>'''
    xml = SHIP.format(sockets).replace('</Ship>', '''<TemplateMissileTypes><MissileTemplate><Designation>SGM-1</Designation>
    <Nickname>Test</Nickname><Load><MagSaveData><MunitionKey>Stock/450mm HE Shell</MunitionKey><Quantity>999</Quantity></MagSaveData></Load>
    </MissileTemplate></TemplateMissileTypes></Ship>''')
    snapshot = parse_design(xml.encode())
    assert snapshot['ships'][0]['ammunition'] == {'$MODMIS$/SGM-1 Test': 2, 'Stock/EA12 Chaff Decoy': 3}
    assert snapshot['custom_template_ids'] == ['$MODMIS$/SGM-1 Test']
    assert not review_fleet(snapshot, bundle)['unknown_ids']
    assert snapshot['ships'][0]['sockets'][0] == {'key': 'beam', 'component': 'Stock/Mk600 Beam Cannon'}


def test_fleet_local_templates_are_identity_not_loaded_inventory():
    xml = '<Fleet><Ships>' + SHIP.format(BEAM) + '</Ships><MissileTypes><MissileTemplate><Designation>X</Designation><Nickname>Y</Nickname></MissileTemplate></MissileTypes></Fleet>'
    snapshot = parse_fleet(xml.encode())
    assert snapshot['custom_template_ids'] == ['$MODMIS$/X Y']
    assert snapshot['ships'][0]['ammunition'] == {}


def test_duplicate_keys_and_negative_ammunition_are_rejected():
    with pytest.raises(FleetInputError, match='duplicate socket'):
        parse_design(SHIP.format(BEAM + BEAM).encode())
    with pytest.raises(FleetInputError, match='duplicate ship'):
        parse_fleet(('<Fleet><Ships>' + SHIP.format('') * 2 + '</Ships></Fleet>').encode())
    socket = '<HullSocket><ComponentName>Stock/Bulk Magazine</ComponentName><ComponentData><Load><MagSaveData><MunitionKey>Stock/450mm AP Shell</MunitionKey><Quantity>-1</Quantity></MagSaveData></Load></ComponentData></HullSocket>'
    with pytest.raises(FleetInputError, match='nonnegative integer'):
        parse_design(SHIP.format(socket).encode())


def test_ship_templates_are_distinct_from_fleet_input():
    with pytest.raises(FleetInputError, match='Fleet XML'):
        parse_fleet(SHIP.format('').encode())
    snapshot = parse_design(SHIP.format('').replace('<Key>', '<Cost>450</Cost><Key>').encode())
    assert snapshot['kind'] == 'ship' and snapshot['declared_points'] == 450


def test_unknown_or_missing_catalog_never_establishes_absence(bundle):
    snapshot = parse_design(SHIP.format(BEAM).encode())
    bundle['catalog']['components'] = {}
    result = review_fleet(snapshot, bundle)
    assert result['findings'] == []
    assert 'Stock/Mk600 Beam Cannon' in result['unknown_ids']
    assert any('Incomplete catalog' in line for line in result['limitations'])


def test_unknown_predicate_skips_visibly_and_never_executes(bundle):
    snapshot = parse_design(SHIP.format(BEAM).encode())
    check = copy.deepcopy(bundle['checks'][0])
    check['when'] = [{'run': 'print("wrong")'}]
    bundle['checks'] = [check]
    result = review_fleet(snapshot, bundle)
    assert not result['findings']
    assert any('unsupported predicate run' in line for line in result['limitations'])


def test_unsupported_schema_and_bad_argument_types(bundle):
    snapshot = parse_design(SHIP.format('').encode())
    with pytest.raises(FleetInputError, match='collection'):
        review_fleet(snapshot, bundle, excluded_entry_ids='fb-001')
    with pytest.raises(FleetInputError, match='Unknown review role'):
        review_fleet(snapshot, bundle, role='auto')
    with pytest.raises(FleetInputError, match='investment'):
        review_fleet(snapshot, bundle, investment='invincible')
    bundle['schema_version'] = 999
    with pytest.raises(BundleError, match='Unsupported'):
        review_fleet(snapshot, bundle)

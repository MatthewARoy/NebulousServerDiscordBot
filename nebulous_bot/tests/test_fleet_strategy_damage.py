"""Conditional packet/DT arithmetic, grounded in the shipped damage evidence.

These tests specify a caller-declared hit collection. They do not treat the
order of fittings in a save as evidence of physical adjacency or penetration.
"""

import copy
import json
from pathlib import Path
import shutil

import pytest

from fleet_strategy import FleetInputError, load_bundle, parse_design, review_fleet
from fleet_strategy.__main__ import main
from fleet_strategy.damage import MAX_STACK_PARTS, damage_inventory, destruction_gate, evaluate_stack


ROOT = Path(__file__).resolve().parents[2]
CIC = "Stock/Reinforced CIC"
DC = "Stock/Reinforced DC Locker"
MAGAZINE = "Stock/Reinforced Magazine"


@pytest.fixture
def bundle():
    return load_bundle(ROOT / "knowledge")


def design(*components):
    sockets = "".join(
        f"<HullSocket><Key>{key}</Key><ComponentName>{component}</ComponentName></HullSocket>"
        for key, component in components
    )
    return parse_design(
        ("<Ship><Key>s</Key><Name>Stack example</Name>"
         "<HullType>Stock/Axford Heavy Cruiser</HullType>"
         f"<SocketMap>{sockets}</SocketMap></Ship>").encode()
    )


def evaluate(fleet, bundle, *, keys=("a",), threat="hei", reduction=0):
    return evaluate_stack(
        fleet, bundle, ship_key="s", socket_keys=list(keys),
        threat_id=threat, damage_reduction=reduction,
    )


def packets(result):
    return [recipient["packet"] for recipient in result["recipients"]]


@pytest.mark.parametrize(
    ("reduction", "packet", "status", "exceeded"),
    [(0, 50, "threshold-exceeded", True),
     (0.2, 40, "conditional-below-dt", False),
     (0.3, 35, "conditional-below-dt", False)],
)
def test_hei_maximum_packet_and_strict_threshold(bundle, reduction, packet, status, exceeded):
    result = evaluate(design(("a", CIC)), bundle, reduction=reduction)
    assert result["status"] == status
    assert packets(result) == pytest.approx([packet])
    assert result["recipients"][0]["threshold"] == 40
    assert result["recipients"][0]["exceeds_threshold"] is exceeded
    assert result["bundle_id"] == bundle["bundle_id"]
    assert result["assumptions"]
    assert result["limitations"]


def test_only_explicitly_selected_components_share_the_packet(bundle):
    fleet = design(("a", CIC), ("b", MAGAZINE), ("c", DC))
    one = evaluate(fleet, bundle)
    two = evaluate(fleet, bundle, keys=("a", "b"))
    assert packets(one) == [50]
    assert packets(two) == [25, 25]
    assert [row["socket_key"] for row in two["recipients"]] == ["a", "b"]
    assert two["status"] == "conditional-below-dt"


def test_mixed_thresholds_are_checked_individually_not_added(bundle):
    result = evaluate(design(("a", CIC), ("b", DC)), bundle,
                      keys=("a", "b"), threat="250-he")
    assert packets(result) == [40, 40]
    assert [row["threshold"] for row in result["recipients"]] == [40, 35]
    assert [row["exceeds_threshold"] for row in result["recipients"]] == [False, True]
    assert result["status"] == "threshold-exceeded"


@pytest.mark.parametrize(("threat", "packet"),
                         [("120-he", 50), ("250-he", 80), ("450-he", 150), ("600-hesh", 60)])
def test_documented_even_spread_profiles_are_per_packet(bundle, threat, packet):
    result = evaluate(design(("a", CIC), ("b", MAGAZINE)), bundle,
                      keys=("a", "b"), threat=threat)
    assert packets(result) == [packet / 2, packet / 2]


@pytest.mark.parametrize("reduction", [0, 0.9])
def test_rail_falloff_uses_declared_hit_order_remaining_pool_and_ignores_dr(bundle, reduction):
    # Save order is a,b,c; the caller supplies the hypothetical hit order c,a,b.
    result = evaluate(design(("a", CIC), ("b", MAGAZINE), ("c", DC)), bundle,
                      keys=("c", "a", "b"), threat="300-rail", reduction=reduction)
    assert [row["socket_key"] for row in result["recipients"]] == ["c", "a", "b"]
    assert packets(result) == [40, 20, 10]
    assert [row["exceeds_threshold"] for row in result["recipients"]] == [True, False, False]


def test_fracturing_cannot_be_called_harmless_to_all_components(bundle):
    # New audit correction: a 15-damage ray can exceed Mount Gyros' DT10.
    # It ignores hull DR; reinforced CIC's DT40 is a different outcome.
    low_dt = evaluate(design(("a", "Stock/Mount Gyros")), bundle,
                      threat="500-fracturing", reduction=0.9)
    high_dt = evaluate(design(("a", CIC)), bundle,
                       threat="500-fracturing", reduction=0.9)
    assert packets(low_dt) == packets(high_dt) == [15]
    assert low_dt["status"] == "threshold-exceeded"
    assert high_dt["status"] == "conditional-below-dt"


def test_ap_does_not_evenly_share_with_later_selected_recipients(bundle):
    result = evaluate(design(("a", CIC), ("b", DC)), bundle,
                      keys=("b", "a"), threat="450-ap", reduction=0.2)
    assert result["recipients"][0]["socket_key"] == "b"
    assert packets(result) == [80, 0]
    assert result["status"] == "threshold-exceeded"


def test_unknown_profile_or_component_withholds_reassuring_numbers(bundle):
    examples = [
        (design(("a", CIC)), "modded-warhead"),
        (design(("a", "ExampleMod/Reinforced CIC")), "hei"),
        (design(("a", "Stock/Mk600 Beam Cannon")), "hei"),
    ]
    for fleet, threat in examples:
        result = evaluate(fleet, bundle, threat=threat)
        assert result["status"] == "unknown"
        assert result["limitations"]
        assert all(row.get("packet") is None for row in result["recipients"])


def test_unknown_member_does_not_silently_increase_the_divisor(bundle):
    result = evaluate(design(("a", CIC), ("b", "ExampleMod/Shield")), bundle, keys=("a", "b"))
    assert result["status"] == "unknown"
    assert all(row.get("packet") is None for row in result["recipients"])


@pytest.mark.parametrize("invalid_model", [None, {}, {"schema_version": 999}])
def test_missing_or_unsupported_damage_model_is_unknown(bundle, invalid_model):
    bundle["damage_model"] = invalid_model
    result = evaluate(design(("a", CIC)), bundle)
    assert result["status"] == "unknown"
    assert all(row.get("packet") is None for row in result["recipients"])


@pytest.mark.parametrize("target", ["catalog", "mechanics"])
def test_version_mismatch_prevents_reassuring_calculations(bundle, target):
    if target == "catalog":
        bundle["catalog_version"] = "different-game-build"
    else:
        bundle["damage_model"]["game_version"] = "different-game-build"
    result = evaluate(design(("a", CIC)), bundle)
    assert result["status"] == "unknown"
    assert all(row.get("packet") is None for row in result["recipients"])


def test_stock_damage_records_carry_pinned_source_evidence(bundle):
    model = bundle["damage_model"]
    assert model["game_version"] == bundle["catalog_version"] == "0.6.2.6-public-steam25104609"
    assert model["evidence"]
    assert model["limitations"]
    for record in model["components"] + model["threats"]:
        assert record["source"]
        digest = record["source_sha256"]
        assert len(digest) == 64
        assert all(character in "0123456789abcdef" for character in digest)


def test_damage_model_content_participates_in_bundle_hash(tmp_path):
    for folder in ("catalog", "entries", "strategy"):
        shutil.copytree(ROOT / "knowledge" / folder, tmp_path / folder)
    original = load_bundle(tmp_path)
    assert load_bundle(tmp_path)["bundle_id"] == original["bundle_id"]
    model_path = tmp_path / "strategy" / "damage.toml"
    source = model_path.read_text(encoding="utf-8")
    assert "threshold = 35" in source
    model_path.write_text(source.replace("threshold = 35", "threshold = 36", 1), encoding="utf-8")
    changed = load_bundle(tmp_path)
    assert changed["bundle_id"] != original["bundle_id"]
    assert changed["damage_model"] != original["damage_model"]
    model_path.unlink()
    missing = load_bundle(tmp_path)
    assert missing["bundle_id"] != original["bundle_id"]
    assert evaluate(design(("a", CIC)), missing)["status"] == "unknown"


@pytest.mark.parametrize(("original", "malformed"), [
    ('distribution = "even"', 'distribution = []'),
    ('packet_damage = 50', 'packet_damage = nan'),
    ('packet_damage = 50', 'packet_damage = inf'),
])
def test_malformed_optional_damage_model_is_quarantined_without_losing_community_review(tmp_path, original, malformed):
    for folder in ("catalog", "entries", "strategy"):
        shutil.copytree(ROOT / "knowledge" / folder, tmp_path / folder)
    model_path = tmp_path / "strategy" / "damage.toml"
    source = model_path.read_text(encoding="utf-8")
    assert original in source
    model_path.write_text(source.replace(original, malformed, 1), encoding="utf-8")

    bundle = load_bundle(tmp_path)
    assert bundle["damage_model"] == {}
    assert bundle["diagnostics"]
    assert len(bundle["bundle_id"]) == 64
    json.dumps(bundle, allow_nan=False)
    fleet = design(("a", CIC), ("b", "Stock/Mk600 Beam Cannon"))
    ordinary_review = review_fleet(fleet, bundle)
    assert any(row["check_id"] == "beam-particle-support" for row in ordinary_review["findings"])
    scenario = evaluate(fleet, bundle)
    assert scenario["status"] == "unknown"
    assert scenario["recipients"] == []


@pytest.mark.parametrize("keys", [[], ["a", "a"], ["missing"], ["a", "missing"], "a", [None], [True]])
def test_invalid_hit_collections_are_rejected(bundle, keys):
    with pytest.raises(FleetInputError):
        evaluate_stack(design(("a", CIC)), bundle, ship_key="s", socket_keys=keys,
                       threat_id="hei", damage_reduction=0)


@pytest.mark.parametrize("ship_key", ["missing", "", None, True])
def test_invalid_ship_selection_is_rejected(bundle, ship_key):
    with pytest.raises(FleetInputError):
        evaluate_stack(design(("a", CIC)), bundle, ship_key=ship_key, socket_keys=["a"],
                       threat_id="hei", damage_reduction=0)


@pytest.mark.parametrize("reduction", [-0.01, 0.91, float("nan"), float("inf"), -float("inf"), True, None, "0.2"])
def test_damage_reduction_must_be_explicit_finite_numeric_fraction(bundle, reduction):
    with pytest.raises(FleetInputError):
        evaluate(design(("a", CIC)), bundle, reduction=reduction)


@pytest.mark.parametrize("reduction", [0, 0.9])
def test_damage_reduction_closed_interval_endpoints_are_valid(bundle, reduction):
    assert evaluate(design(("a", CIC)), bundle, reduction=reduction)["status"] != "unknown"


def test_evaluation_does_not_mutate_the_parsed_fleet_or_shared_bundle(bundle):
    fleet = design(("a", CIC), ("b", DC))
    original_fleet, original_bundle = copy.deepcopy(fleet), copy.deepcopy(bundle)
    evaluate(fleet, bundle, keys=("b", "a"), threat="300-rail")
    assert fleet == original_fleet
    assert bundle == original_bundle


def test_inventory_lists_supported_reinforced_socket_ids_without_grouping(bundle):
    fleet = design(("a", CIC), ("b", "Stock/Mount Gyros"), ("c", DC))
    assert damage_inventory(fleet, bundle) == [{
        "ship_key": "s", "ship_name": "Stack example", "sockets": [
            {"key": "a", "component": CIC, "threshold": 40},
            {"key": "c", "component": DC, "threshold": 35},
        ],
    }]
    bundle["catalog_version"] = "different-game-build"
    assert damage_inventory(fleet, bundle) == []


@pytest.mark.parametrize("unknown_content", ["hull", "component"])
def test_inventory_withholds_stock_thresholds_when_ship_applicability_is_unknown(bundle, unknown_content):
    fleet = design(("a", CIC), ("b", DC))
    if unknown_content == "hull":
        fleet["ships"][0]["hull"] = "ExampleMod/Heavy Cruiser"
    else:
        fleet["ships"][0]["sockets"][1]["component"] = "ExampleMod/Reinforced DC Locker"
    assert damage_inventory(fleet, bundle) == []


def test_selected_hit_collection_has_an_enforced_size_bound(bundle):
    keys = [f"s{i}" for i in range(MAX_STACK_PARTS + 1)]
    fleet = design(*[(key, CIC) for key in keys])
    assert len(evaluate(fleet, bundle, keys=keys[:-1])["recipients"]) == MAX_STACK_PARTS
    with pytest.raises(FleetInputError):
        evaluate(fleet, bundle, keys=keys)


@pytest.fixture
def design_file(tmp_path):
    path = tmp_path / "stack.ship"
    path.write_text(
        '<Ship><Key>s</Key><Name>Example</Name><HullType>Stock/Axford Heavy Cruiser</HullType>'
        '<SocketMap><HullSocket><Key>a</Key><ComponentName>Stock/Reinforced CIC</ComponentName></HullSocket>'
        '<HullSocket><Key>b</Key><ComponentName>Stock/Reinforced Magazine</ComponentName></HullSocket>'
        '</SocketMap></Ship>', encoding="utf-8",
    )
    return path


def test_cli_applies_all_explicit_scenario_flags_and_preserves_design(design_file, capsys):
    original = design_file.read_bytes()
    exit_code = main([
        "--knowledge", str(ROOT / "knowledge"), "review", str(design_file),
        "--stack", "s:b,a", "--threat", "250-he", "--dr", "0.5",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert not captured.err
    scenario = json.loads(captured.out)["damage_scenario"]
    assert scenario["ship_key"] == "s"
    assert scenario["socket_keys"] == ["b", "a"]
    assert scenario["threat"]["id"] == "250-he"
    assert scenario["damage_reduction"] == 0.5
    assert packets(scenario) == [20, 20]
    assert scenario["status"] == "conditional-below-dt"
    assert design_file.read_bytes() == original


@pytest.mark.parametrize("flags", [
    ["--stack", "s:a"], ["--dr", "0.2"],
    ["--stack", "s:a", "--threat", "hei"],
    ["--stack", "s:a", "--dr", "0.2"],
    ["--threat", "hei", "--dr", "0.2"],
    ["--stack", "a", "--threat", "hei", "--dr", "0.2"],
])
def test_cli_requires_complete_explicit_scenario_options(design_file, capsys, flags):
    exit_code = main(["--knowledge", str(ROOT / "knowledge"), "review", str(design_file), *flags])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "together" in captured.err
    assert not captured.out


def test_cli_threat_and_direction_select_automatic_review(design_file, capsys):
    assert main(["--knowledge", str(ROOT / "knowledge"), "review", str(design_file),
                 "--threat", "250-he", "--direction", "stern"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "damage_scenario" not in report
    assert report["protection"]["threat_id"] == "250-he"
    assert report["protection"]["direction"] == "stern"
    assert report["protection"]["status"] == "unknown"  # No local geometry installed.


def test_exact_registry_ids_are_never_whitespace_normalized(bundle):
    fleet = design(("a", " Stock/Reinforced CIC "))
    assert fleet["ships"][0]["sockets"][0]["component"] == " Stock/Reinforced CIC "
    assert evaluate(fleet, bundle)["status"] == "unknown"


@pytest.mark.parametrize(("packet", "exceeded", "destroyed"), [(39, False, False), (40, False, False), (41, True, True)])
def test_destruction_gate_is_strictly_above_dt(packet, exceeded, destroyed):
    result = destruction_gate(packet, 40, current_health=0, reinforced=True)
    assert result["threshold_exceeded"] is exceeded
    assert result["destroyed"] is destroyed
    assert result["resulting_health"] == 0


def test_exceeding_dt_alone_does_not_destroy_a_part_with_remaining_health():
    result = destruction_gate(41, 40, current_health=100)
    assert result == {"resulting_health": 59, "threshold_exceeded": True, "destroyed": False}


def test_accumulated_frame_damage_controls_remaining_hp_not_packet_threshold():
    result = destruction_gate(1, 40, current_health=100, pending_damage=99)
    assert result == {"resulting_health": 0, "threshold_exceeded": False, "destroyed": False}
    above_dt = destruction_gate(41, 40, current_health=100, pending_damage=59)
    assert above_dt == {"resulting_health": 0, "threshold_exceeded": True, "destroyed": True}


def test_reinforced_part_requires_already_zero_committed_health():
    fresh = destruction_gate(1000, 40, current_health=100, reinforced=True)
    same_frame = destruction_gate(1000, 40, current_health=100, pending_damage=1000, reinforced=True)
    next_frame = destruction_gate(41, 40, current_health=0, reinforced=True)
    assert fresh["resulting_health"] == same_frame["resulting_health"] == 0
    assert fresh["destroyed"] is same_frame["destroyed"] is False
    assert next_frame["destroyed"] is True

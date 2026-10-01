"""Conditional regional findings over synthetic geometry, never combat certainty."""

import copy

import pytest

from fleet_strategy.geometry import build_fingerprint, geometry_fingerprint, geometry_problem
from fleet_strategy.protection import overlay_projection, review_protection


CIC = "Stock/Reinforced CIC"
WEAK = "Stock/Basic CIC"
FILLER = "Stock/Reinforced Magazine"
HULL = "Synthetic/Hull"
VERSION = "synthetic-audit-1"


def box(center=(0, 0, 0)):
    return {"center": list(center), "half_extents": [.5, .5, .5], "rotation": [0, 0, 0, 1]}


def socket(center=(0, 0, 0)):
    return {**box(center), "type": 1, "size": [4, 4, 4], "layer": 11, "interior_overhang": 0}


def stamp(data):
    data["geometry_id"] = geometry_fingerprint(data)
    assert geometry_problem(data) is None
    return data


def design(*fittings):
    return {"name": "Synthetic fleet", "kind": "fleet", "faction": "ans", "declared_points": 0,
            "ships": [{"key": "ship", "name": "Synthetic ship", "hull": HULL,
                       "sockets": [{"key": key, "component": part} for key, part in fittings],
                       "components": [part for _, part in fittings if part], "ammunition": {},
                       "hull_config": None, "declared_points": 0}]}


@pytest.fixture
def bundle():
    source = {"source": "synthetic test fixture", "source_sha256": "a" * 64}
    components = [{"id": key, "threshold": dt, "max_health": 100, "reinforced": key != WEAK, **source}
                  for key, dt in ((CIC, 40), (WEAK, 10), (FILLER, 40))]
    threats = [
        {"id": "hei", "geometry_mode": "ray", "geometry_distance": 7, "packet_damage": 50,
         "distribution": "even"},
        {"id": "450-he", "geometry_mode": "explosion", "geometry_radius": 1.5, "packet_damage": 60,
         "distribution": "even"},
        {"id": "450-ap", "geometry_mode": "ray", "geometry_distance": 11, "packet_damage": 60,
         "distribution": "first"},
        {"id": "unsupported", "packet_damage": 50, "distribution": "even"},
    ]
    for profile in threats:
        profile.update(source, ignores_dr=False, label="Synthetic " + profile["id"],
                       assumption="Hypothetical internal damage only.")
    return {"bundle_id": "synthetic-bundle-1", "catalog_version": VERSION,
            "catalog": {"hulls": {HULL: "Synthetic hull"}, "components": {key: key for key in (CIC, WEAK, FILLER)}},
            "damage_model": {"schema_version": 1, "game_version": VERSION, "components": components,
                             "threats": threats, "evidence": ["Synthetic arithmetic fixture."],
                             "limitations": ["Not stock data or combat validation."]}}


@pytest.fixture
def geometry():
    return stamp({
        "schema_version": 1, "game_version": VERSION, "provenance": ["Synthetic boxes only."],
        "hulls": {HULL: {
            "faction": "ans", "bounds": {"center": [0, 0, 0], "half_extents": [3, 3, 3]},
            "sockets": {"target": socket(), "front": socket((0, 0, 1.5)), "side": socket((1.5, 0, 0))},
            "other_colliders": [], "unsupported": [], "min_component_dr": 0, "max_component_dr": 0,
            "sphere_query_complete": True,
        }},
        "components": {key: {"type": 1, "size": [4, 4, 4], "rotate_to_fit": 0, "can_tile": False,
                             "interior_overhang": 0, "point_cost": 10, "faction": "ans"}
                       for key in (CIC, WEAK, FILLER)},
    })


def parts(report, ship=0):
    return {row["socket_key"]: row for row in report["ships"][ship]["parts"]}


def collider(kind="part", *, exact=True, threshold=40):
    return {**box((0, 0, 1.5)), "collider_id": "extra", "recipient_id": "hull-part", "kind": kind,
            "shape": "box", "exact": exact, "base_dt": threshold, "reinforced": True}


def overlay(report, **changes):
    request = {key: report[key] for key in ("build_id", "geometry_id", "bundle_id", "threat_id", "direction")}
    return overlay_projection(report, **(request | changes))


def test_synthetic_stack_retains_per_target_packets_and_conditional_scope(bundle, geometry):
    fleet = design(("target", CIC), ("front", FILLER))
    report = review_protection(fleet, bundle, geometry)
    assert report["status"] == "assessed"
    assert report["build_id"] == build_fingerprint(fleet)
    assert report["geometry_id"] == geometry["geometry_id"]
    assert report["bundle_id"] == bundle["bundle_id"]
    assert report["provenance"] == geometry["provenance"]
    assert "assumed" in report["evidence_scope"]
    assert any("HP loss" in limitation for limitation in report["limitations"])
    for key, row in parts(report).items():
        assert row["status"] == "within-dt"
        assert (row["worst_packet"], row["threshold"], row["margin"]) == (25, 40, 15)
        assert (row["tested_paths"], row["unknown_paths"]) == (5, 0)
        assert row["supporting_sockets"] == ["front" if key == "target" else "target"]
        assert row["support_status"] == "within-dt"
        assert all(path["recipients"] == ["front", "target"] for path in row["paths"])


def test_structure_is_excluded_from_recipient_divisor(bundle, geometry):
    geometry["hulls"][HULL]["other_colliders"] = [collider("structure")]
    stamp(geometry)
    report = review_protection(design(("target", CIC)), bundle, geometry)
    target = parts(report)["target"]
    assert target["worst_packet"] == 50
    assert target["status"] == "threshold-exceeded"
    assert target["supporting_sockets"] == []
    assert all(path["recipients"] == ["target"] for path in target["paths"])


def test_sphere_neighbors_participate_without_being_on_the_ray(bundle, geometry):
    fleet = design(("target", CIC), ("side", FILLER))
    ray = parts(review_protection(fleet, bundle, geometry))["target"]
    sphere = parts(review_protection(fleet, bundle, geometry, threat_id="450-he"))["target"]
    assert ray["worst_packet"] == 50 and ray["supporting_sockets"] == []
    assert sphere["worst_packet"] == 30 and sphere["supporting_sockets"] == ["side"]
    assert sphere["status"] == "within-dt"
    assert all(path["geometry"]["radius"] == 1.5 for path in sphere["paths"])


@pytest.mark.parametrize("complete", [False, None])
def test_unverified_sphere_query_capacity_withholds_explosion_results(bundle, geometry, complete):
    hull = geometry["hulls"][HULL]
    if complete is None:
        hull.pop("sphere_query_complete")
    else:
        hull["sphere_query_complete"] = complete
    stamp(geometry)
    report = review_protection(design(("target", CIC), ("side", FILLER)), bundle, geometry, threat_id="450-he")
    assert report["status"] == "unknown"
    assert all(row["status"] == "unknown" and row["tested_paths"] == 0 for row in parts(report).values())
    assert report["ships"][0]["suggestions"] == []


def test_finite_ray_not_reaching_target_is_unknown_not_protection(bundle, geometry):
    geometry["hulls"][HULL]["bounds"]["half_extents"][2] = 10
    stamp(geometry)
    report = review_protection(design(("target", CIC)), bundle, geometry)
    target = parts(report)["target"]
    assert target["status"] == "unknown"
    assert target["worst_packet"] is None and target["margin"] is None
    assert (target["tested_paths"], target["unknown_paths"]) == (0, 5)
    assert all(path["geometry"]["length"] == 7 for path in target["paths"])
    assert report["ships"][0]["suggestions"] == []
    assert overlay(report)["parts"][0]["color"] == "grey"


@pytest.mark.parametrize(("kind", "exact"), [("part", False), ("unknown", True), ("unknown", False)])
def test_uncertain_nonstructural_collider_withholds_result(bundle, geometry, kind, exact):
    geometry["hulls"][HULL]["other_colliders"] = [collider(kind, exact=exact)]
    stamp(geometry)
    target = parts(review_protection(design(("target", CIC)), bundle, geometry))["target"]
    assert target["status"] == "unknown" and target["unknown_paths"] == 5
    assert target["worst_packet"] is None


@pytest.mark.parametrize(("threshold", "expected", "color"), [(10, "vulnerable", "amber"),
                                                             (None, "unknown", "grey"),
                                                             (40, "within-dt", "blue")])
def test_target_protection_is_separate_from_hull_part_support(bundle, geometry, threshold, expected, color):
    geometry["hulls"][HULL]["other_colliders"] = [collider(threshold=threshold)]
    stamp(geometry)
    report = review_protection(design(("target", CIC)), bundle, geometry)
    target = parts(report)["target"]
    assert target["status"] == "within-dt" and target["worst_packet"] == 25
    assert target["supporting_sockets"] == ["@hull:extra"]
    assert target["support_status"] == expected
    projection = overlay(report)
    assert projection["parts"][0]["color"] == color
    assert projection["parts"][0]["status"] == "within-dt"
    assert projection["parts"][0]["support_status"] == expected
    assert projection["parts"][0]["tested_paths"] == 5
    assert projection["parts"][0]["unknown_paths"] == 0
    assert set(projection["legend"]) == {"blue", "amber", "grey"}
    assert "not immunity" in projection["legend"]["blue"]


def test_target_protection_does_not_hide_vulnerable_fitted_support(bundle, geometry):
    report = review_protection(design(("target", CIC), ("front", WEAK)), bundle, geometry)
    rows = parts(report)
    assert rows["target"]["status"] == "within-dt"
    assert rows["target"]["support_status"] == "vulnerable"
    assert rows["front"]["status"] == "threshold-exceeded"
    assert rows["front"]["worst_packet"] == rows["target"]["worst_packet"] == 25
    colors = {row["socket_key"]: row["color"] for row in overlay(report)["parts"]}
    assert colors == {"target": "amber", "front": "amber"}


def test_ap_uses_first_recipient_and_rejects_ambiguous_ties(bundle, geometry):
    fleet = design(("target", CIC), ("front", FILLER))
    report = review_protection(fleet, bundle, geometry, threat_id="450-ap")
    rows = parts(report)
    assert rows["front"]["worst_packet"] == 60
    assert rows["target"]["worst_packet"] == 0
    assert rows["target"]["support_status"] == "vulnerable"
    geometry["hulls"][HULL]["sockets"]["front"]["center"] = [0, 0, 0]
    stamp(geometry)
    ambiguous = parts(review_protection(fleet, bundle, geometry, threat_id="450-ap"))
    assert all(row["status"] == "unknown" for row in ambiguous.values())
    assert all("ambiguous" in row["reason"] for row in ambiguous.values())


def test_suggestions_improve_target_without_mutating_input_and_check_filler(bundle, geometry):
    fleet = design(("target", CIC), ("front", None))
    before = copy.deepcopy((fleet, bundle, geometry))
    report = review_protection(fleet, bundle, geometry)
    assert (fleet, bundle, geometry) == before
    candidates = report["ships"][0]["suggestions"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["socket_key"] == "front" and candidate["component"] == FILLER
    assert candidate["target_sockets"] == ["target"]
    assert candidate["before_margin"] == -10 and candidate["after_margin"] == 15
    assert candidate["changes"] == [{"socket_key": "front", "from": None, "to": FILLER}]
    assert candidate["status"] == "candidate" and candidate["limitations"]
    proposed = design(("target", CIC), ("front", FILLER))
    applied = parts(review_protection(proposed, bundle, geometry))
    assert all(row["status"] == "within-dt" and row["unknown_paths"] == 0 for row in applied.values())


def test_suggestions_reject_filler_whose_own_probes_fail(bundle, geometry):
    # The wider filler helps all target rays, but its outboard sample rays miss
    # the small target and would hit only itself (50 > 40 DT).
    geometry["hulls"][HULL]["sockets"]["front"]["half_extents"][0] = 2
    stamp(geometry)
    report = review_protection(design(("target", CIC)), bundle, geometry)
    assert report["ships"][0]["suggestions"] == []
    with_filler = parts(review_protection(design(("target", CIC), ("front", FILLER)), bundle, geometry))
    assert with_filler["target"]["status"] == "within-dt"
    assert with_filler["front"]["status"] == "threshold-exceeded"


@pytest.mark.parametrize("support_status", ["vulnerable", "unknown"])
def test_suggestions_do_not_rely_on_vulnerable_or_unaudited_support(bundle, geometry, support_status):
    # A fourth recipient would reduce packets from 50 to 37.5, enough for the
    # target and new magazine. Existing weak/unaudited support prevents this
    # conditional improvement from becoming a recommended candidate.
    hull = geometry["hulls"][HULL]
    hull["sockets"]["side"]["center"] = [0, 0, -1.5]
    hull["sockets"]["addition"] = socket((0, 0, 2.4))
    stamp(geometry)
    bundle["damage_model"]["threats"][0]["packet_damage"] = 150
    if support_status == "unknown":
        bundle["damage_model"]["components"] = [
            row for row in bundle["damage_model"]["components"] if row["id"] != WEAK
        ]
    baseline_fit = (("target", CIC), ("front", WEAK), ("side", FILLER))
    report = review_protection(design(*baseline_fit), bundle, geometry)
    assert parts(report)["target"]["worst_packet"] == 50
    assert report["ships"][0]["suggestions"] == []
    proposed = review_protection(design(*baseline_fit, ("addition", FILLER)), bundle, geometry)
    for key in ("target", "addition"):
        row = parts(proposed)[key]
        assert row["status"] == "within-dt"
        assert row["worst_packet"] == 37.5 and row["unknown_paths"] == 0
        assert row["support_status"] == support_status


@pytest.mark.parametrize("field", ["build_id", "geometry_id", "bundle_id", "threat_id", "direction"])
def test_overlay_withholds_stale_colors_and_support_for_any_revision_change(bundle, geometry, field):
    report = review_protection(design(("target", CIC), ("front", FILLER)), bundle, geometry)
    assert overlay(report)["current"]
    stale = overlay(report, **{field: "changed"})
    assert not stale["current"]
    assert all(row["status"] == "unknown" and row["color"] == "grey" for row in stale["parts"])
    assert all(row["margin"] is None and row["supporting_sockets"] == [] for row in stale["parts"])
    assert all("recompute" in row["reason"] for row in stale["parts"])


def test_overlay_rejects_results_from_a_different_evaluator_version(bundle, geometry):
    report = review_protection(design(("target", CIC), ("front", FILLER)), bundle, geometry)
    report["engine_version"] = "older-engine"
    stale = overlay(report)
    assert not stale["current"]
    assert all(row["color"] == "grey" and row["margin"] is None for row in stale["parts"])


@pytest.mark.parametrize("bad_bundle", [None, {}, {"damage_model": None},
                                         {"damage_model": {"threats": [None]}},
                                         {"damage_model": {"threats": [{}]}}])
def test_malformed_source_bundle_produces_unknown_instead_of_crashing(geometry, bad_bundle):
    report = review_protection(design(("target", CIC)), bad_bundle, geometry)
    assert report["status"] == "unknown"
    assert parts(report)["target"]["status"] == "unknown"
    assert report["ships"][0]["suggestions"] == []


@pytest.mark.parametrize("field", ["bundle_id", "geometry_id"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), .5])
def test_malformed_source_identifiers_fail_closed_before_assessment_hashing(bundle, geometry, field, value):
    source = bundle if field == "bundle_id" else geometry
    source[field] = value
    report = review_protection(design(("target", CIC)), bundle, geometry)
    assert report["status"] == "unknown"
    assert report[field] is None
    assert parts(report)["target"]["tested_paths"] == 0
    assert report["ships"][0]["suggestions"] == []


@pytest.mark.parametrize("failure", ["missing", "stale-hash", "game-version", "nan-center"])
def test_missing_mismatched_or_malformed_geometry_stays_unknown(bundle, geometry, failure):
    if failure == "missing":
        geometry = None
    elif failure == "stale-hash":
        geometry["hulls"][HULL]["sockets"]["target"]["center"][0] += .1
    elif failure == "game-version":
        geometry["game_version"] = "different"
        stamp(geometry)
    else:
        geometry["hulls"][HULL]["sockets"]["target"]["center"][0] = float("nan")
    report = review_protection(design(("target", CIC)), bundle, geometry)
    assert report["status"] == "unknown"
    assert parts(report)["target"]["tested_paths"] == 0


@pytest.mark.parametrize("threat", ["unsupported", "unrecognized"])
def test_unsupported_profile_remains_unknown(bundle, geometry, threat):
    report = review_protection(design(("target", CIC)), bundle, geometry, threat_id=threat)
    assert report["status"] == "unknown"
    assert "sampler" in report["summary"]


@pytest.mark.parametrize(("field", "value"), [("geometry_mode", []), ("geometry_distance", float("nan")),
                                               ("geometry_distance", 0), ("geometry_distance", 101)])
def test_invalid_geometry_profile_parameters_fail_closed(bundle, geometry, field, value):
    bundle["damage_model"]["threats"][0][field] = value
    report = review_protection(design(("target", CIC)), bundle, geometry)
    assert report["status"] == "unknown"
    assert parts(report)["target"]["tested_paths"] == 0


@pytest.mark.parametrize("failure", ["unknown-hull", "missing-socket", "fit", "hull-modifier", "part-modifier", "incomplete"])
def test_unsupported_build_geometry_or_stats_is_not_guessed(bundle, geometry, failure):
    fleet = design(("target", CIC))
    if failure == "unknown-hull":
        fleet["ships"][0]["hull"] = "Modded/Unknown"
    elif failure == "missing-socket":
        fleet["ships"][0]["sockets"][0]["key"] = "missing"
    elif failure == "fit":
        geometry["components"][CIC]["size"] = [99, 99, 99]
    elif failure == "hull-modifier":
        geometry["hulls"][HULL]["stat_modifiers"] = [{"stat": "DT", "modifier": .1}]
    elif failure == "part-modifier":
        geometry["components"][CIC]["stat_modifiers"] = [{"stat": "DT", "modifier": .1}]
    else:
        geometry["hulls"][HULL]["unsupported"] = ["Unresolved geometry fixture"]
    stamp(geometry)
    report = review_protection(fleet, bundle, geometry)
    assert report["status"] == "unknown"
    assert report["ships"][0]["suggestions"] == []


def test_probe_budget_is_global_and_exhaustion_preserves_unknown_rows(bundle, geometry, monkeypatch):
    monkeypatch.setattr("fleet_strategy.protection.MAX_PROBES", 6)
    fleet = design(("target", CIC))
    fleet["ships"] *= 3
    fleet["ships"] = [dict(copy.deepcopy(ship), key=f"ship-{index}") for index, ship in enumerate(fleet["ships"])]
    report = review_protection(fleet, bundle, geometry)
    assert report["probes_used"] == 6
    assert sum(len(row["paths"]) for ship in report["ships"] for row in ship["parts"]) == 6
    assert parts(report, 0)["target"]["tested_paths"] == 5
    assert parts(report, 1)["target"]["unknown_paths"] == 4
    assert parts(report, 2)["target"]["status"] == "unknown"
    assert parts(report, 2)["target"]["unknown_paths"] == 5
    assert all(ship["suggestions"] == [] for ship in report["ships"])


def test_recipient_overflow_is_unknown_without_an_unbounded_damage_calculation(bundle, geometry):
    geometry["hulls"][HULL]["other_colliders"] = [
        dict(collider(), collider_id=f"extra-{index}", recipient_id=f"part-{index}") for index in range(512)
    ]
    stamp(geometry)
    report = review_protection(design(("target", CIC)), bundle, geometry)
    target = parts(report)["target"]
    assert target["status"] == "unknown" and target["unknown_paths"] == 5
    assert "buffer" in target["reason"].lower()
    assert report["ships"][0]["suggestions"] == []


@pytest.mark.parametrize("raw_count", [19, 20, 21])
@pytest.mark.parametrize("structure_mode", ["none", "some", "all"])
def test_raw_raycast_buffer_limit_applies_before_filtering_structural_hits(bundle, geometry, raw_count, structure_mode):
    # The fitted target occupies one raw query entry. Structural colliders
    # consume buffer entries even though they cannot dilute component damage.
    extra_count = raw_count - 1
    structure_count = {"none": 0, "some": extra_count // 2, "all": extra_count}[structure_mode]
    geometry["hulls"][HULL]["other_colliders"] = [
        dict(collider("structure" if index < structure_count else "part"),
             collider_id=f"raw-{index}", recipient_id=f"recipient-{index}")
        for index in range(extra_count)
    ]
    stamp(geometry)
    report = review_protection(design(("target", CIC)), bundle, geometry)
    target = parts(report)["target"]
    if raw_count >= 20:
        assert target["status"] == "unknown" and target["unknown_paths"] == 5
        assert target["worst_packet"] is None
        assert "buffer" in target["reason"].lower()
        assert report["ships"][0]["suggestions"] == []
    else:
        recipient_count = raw_count - structure_count
        assert target["tested_paths"] == 5 and target["unknown_paths"] == 0
        assert target["worst_packet"] == pytest.approx(50 / recipient_count)
        assert all(len(path["recipients"]) == recipient_count for path in target["paths"])

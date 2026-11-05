"""Geometry evidence boundaries and transformations, independent of combat claims."""

import copy
import json
import math

import pytest

from fleet_strategy.geometry import (
    DIRECTIONS, MAX_GEOMETRY_BYTES, GeometryError, build_fingerprint, fits_component,
    geometry_fingerprint, geometry_problem, load_geometry, path_from_point, ray_hits,
    region_for_socket, sample_paths, sphere_hits, target_points,
)


def socket(center=(0, 0, 0), half_extents=(1, 1, 1), rotation=(0, 0, 0, 1)):
    return {"center": list(center), "half_extents": list(half_extents), "rotation": list(rotation),
            "type": 1, "size": [2, 2, 2], "layer": 11, "interior_overhang": 0}


@pytest.fixture
def geometry():
    data = {
        "schema_version": 1, "game_version": "test-build", "provenance": ["Synthetic geometry fixture"],
        "hulls": {"test": {
            "bounds": {"center": [0, 0, 0], "half_extents": [4, 4, 9]},
            "sockets": {"front": socket((0, 0, 7)), "target": socket(), "rear": socket((0, 0, -7))},
            "min_component_dr": 0, "max_component_dr": 0.9, "unsupported": [],
        }},
        "components": {"part": {"type": 1, "size": [2, 2, 2], "rotate_to_fit": 0, "can_tile": False,
                                  "interior_overhang": 0, "point_cost": 10, "faction": "ans"}},
    }
    data["geometry_id"] = geometry_fingerprint(data)
    return data


def test_geometry_load_verifies_content_identity_and_schema(tmp_path, geometry):
    path = tmp_path / "geometry.json"
    path.write_text(json.dumps(geometry), encoding="utf-8")
    assert load_geometry(path) == geometry
    assert geometry_problem(geometry) is None
    geometry["hulls"]["test"]["sockets"]["front"]["center"][2] = 6
    path.write_text(json.dumps(geometry), encoding="utf-8")
    with pytest.raises(GeometryError, match="does not match"):
        load_geometry(path)


@pytest.mark.parametrize("raw", [
    '{"schema_version": 1, "schema_version": 1}',
    '{"x":{"same":1,"same":2}}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}',
    '"not an object"', '[' * 1100 + '0' + ']' * 1100,
])
def test_loader_rejects_duplicate_nonfinite_or_unbounded_json(tmp_path, raw):
    path = tmp_path / "geometry.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(GeometryError):
        load_geometry(path)


def test_loader_bounds_read_before_parsing(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (MAX_GEOMETRY_BYTES + 1))
    with pytest.raises(GeometryError, match="8 MiB"):
        load_geometry(path)


@pytest.mark.parametrize(("field", "value"), [
    ("rotation", [0, 0, 0, 2]), ("rotation", [0, 0, 0, 0]),
    ("half_extents", [1, -1, 1]), ("center", [0, float("nan"), 0]),
    ("center", [0, 0, 1e10]), ("size", [2, True, 2]), ("layer", 12),
    ("interior_overhang", -1), ("type", True),
])
def test_invalid_socket_fails_closed(geometry, field, value):
    geometry["hulls"]["test"]["sockets"]["target"][field] = value
    assert geometry_problem(geometry)


def test_rotated_bounds_must_enclose_socket(geometry):
    q = math.sqrt(0.5)
    geometry["hulls"]["test"]["sockets"]["target"] = socket((3, 0, 0), (1, 1, 3), (0, q, 0, q))
    assert "outside declared hull bounds" in geometry_problem(geometry)


def test_other_colliders_preserve_identity_and_approximation(geometry):
    hull = geometry["hulls"]["test"]
    hull["other_colliders"] = [
        {**socket(), "collider_id": "structure-1", "recipient_id": "hullpart-1", "kind": "structure",
         "shape": "box", "exact": True, "base_dt": 10, "reinforced": False},
        {**socket(), "collider_id": "capsule-1", "recipient_id": "hullpart-2", "kind": "part",
         "shape": "capsule", "exact": False, "base_dt": None, "reinforced": None},
    ]
    hull["stat_modifiers"] = {"threshold_multiplier": 1.0}
    geometry["geometry_id"] = geometry_fingerprint(geometry)
    assert geometry_problem(geometry) is None
    hull["other_colliders"][1]["exact"] = True
    assert "cannot be exact" in geometry_problem(geometry)
    hull["other_colliders"][1]["exact"] = False
    hull["other_colliders"].append(copy.deepcopy(hull["other_colliders"][0]))
    assert "unique" in geometry_problem(geometry)


def test_fingerprints_are_order_independent_but_track_all_snapshot_content(geometry):
    assert geometry_fingerprint(dict(reversed(list(geometry.items())))) == geometry["geometry_id"]
    geometry["geometry_id"] = "ignored self reference"
    assert geometry_fingerprint(geometry) != geometry["geometry_id"]
    original = {"ships": [{"sockets": [{"key": "a", "component": "c"}],
                           "hull_config": "variant-a", "component_data": {"ammo": 10}}]}
    identity = build_fingerprint(original)
    for path, value in (("hull_config", "variant-b"), ("component_data", {"ammo": 9}),
                        ("sockets", [{"key": "a", "component": "d"}])):
        changed = copy.deepcopy(original)
        changed["ships"][0][path] = value
        assert build_fingerprint(changed) != identity
    assert build_fingerprint({"b": 2, "a": 1}) == build_fingerprint({"a": 1, "b": 2})
    with pytest.raises(GeometryError):
        build_fingerprint({"invalid": float("nan")})


def test_ray_order_normalization_and_finite_depth(geometry):
    sockets = geometry["hulls"]["test"]["sockets"]
    hits = ray_hits((0, 0, 9), (0, 0, -12), sockets, ["rear", "target", "front"], 18)
    assert [hit["socket_key"] for hit in hits] == ["front", "target", "rear"]
    assert [hit["enter"] for hit in hits] == pytest.approx([1, 8, 15])
    assert [hit["exit"] for hit in hits] == pytest.approx([3, 10, 17])
    assert [hit["socket_key"] for hit in ray_hits((0, 0, 9), (0, 0, -1), sockets, sockets, 7)] == ["front"]
    assert ray_hits((0, 0, 9), (0, 0, -1), sockets, ["front"], 1) == []


def test_rotated_obb_uses_socket_transform_not_axis_aligned_extents():
    q = math.sqrt(0.5)
    rotated = {"rotated": socket((4, 0, 0), (1, 2, 3), (0, q, 0, q))}
    hit = ray_hits((4, 0, 5), (0, 0, -1), rotated, rotated, 10)[0]
    assert (hit["enter"], hit["exit"]) == pytest.approx((4, 6))
    # X=6 is inside the rotated long X extent, despite lying outside local X.
    assert len(ray_hits((6, 0, 5), (0, 0, -1), rotated, rotated, 10)) == 1
    opposite_quaternion = copy.deepcopy(rotated)
    opposite_quaternion["rotated"]["rotation"] = [0, -q, 0, -q]
    assert ray_hits((4, 0, 5), (0, 0, -1), opposite_quaternion, rotated, 10) == [hit]


def test_tangencies_and_empty_socket_do_not_create_recipients():
    sockets = {"a": socket(), "empty": socket((0, 0, 4))}
    assert ray_hits((1, 0, 3), (0, 0, -1), sockets, ["a"], 6) == []
    assert ray_hits((2, 0, 0), (-1, 0, 1), sockets, ["a"], 6) == []
    assert ray_hits((0, 0, 6), (0, 0, -1), sockets, ["a"], 3) == []
    inside = ray_hits((0, 0, 0), (0, 0, 1), sockets, ["a"], 10)
    assert inside == []  # Unity raycasts do not detect the collider containing the origin.


@pytest.mark.parametrize(("origin", "direction", "keys", "length"), [
    ((0, 0, 0), (0, 0, 0), ["a"], 1), ((0, 0, float("inf")), (0, 0, 1), ["a"], 1),
    ((0, 0, 0), (0, 0, 1), ["a", "a"], 1), ((0, 0, 0), (0, 0, 1), ["missing"], 1),
    ((0, 0, 0), (0, 0, 1), ["a"], -1), ((0, 0, 0), (0, 0, 1), ["a"], float("nan")),
])
def test_invalid_queries_cannot_silently_add_or_skip_recipients(origin, direction, keys, length):
    with pytest.raises(GeometryError):
        ray_hits(origin, direction, {"a": socket()}, keys, length)


def test_sphere_intersection_respects_oriented_corners_and_tangency():
    q = math.sqrt(0.5)
    sockets = {"a": socket(), "rotated": socket((5, 0, 0), (1, 1, 3), (0, q, 0, q))}
    assert sphere_hits((0, 0, 0), 0.1, sockets, sockets) == ["a"]
    assert sphere_hits((2, 0, 0), 1, sockets, ["a"]) == []
    assert sphere_hits((2, 2, 0), 1.4, sockets, ["a"]) == []
    assert sphere_hits((2, 2, 0), 1.42, sockets, ["a"]) == ["a"]
    assert sphere_hits((7, 0, 0), 0.1, sockets, sockets) == ["rotated"]
    with pytest.raises(GeometryError):
        sphere_hits((0, 0, 0), float("nan"), sockets, sockets)


@pytest.mark.parametrize("direction_name", list(DIRECTIONS))
def test_paths_start_on_upstream_bounds_plane_and_pass_through_target(geometry, direction_name):
    hull = geometry["hulls"]["test"]
    samples = sample_paths(hull, hull["sockets"], "target", direction_name)
    assert len(samples) == 5
    assert len({tuple(sample["target_point"]) for sample in samples}) == 5
    for sample in samples:
        axis = next(i for i, value in enumerate(sample["direction"]) if value)
        assert sample["origin"][axis] == -sample["direction"][axis] * hull["bounds"]["half_extents"][axis]
        assert sample["length"] == 2 * hull["bounds"]["half_extents"][axis]
        assert "target" in sample["socket_keys"]
        assert len(sample["socket_keys"]) == len(set(sample["socket_keys"]))
    if direction_name == "bow":
        assert samples[0]["socket_keys"] == ["front", "target", "rear"]
    elif direction_name == "stern":
        assert samples[0]["socket_keys"] == ["rear", "target", "front"]


def test_path_bounds_and_region_labels_are_explicit(geometry):
    hull = geometry["hulls"]["test"]
    assert [region_for_socket(hull, key) for key in ("front", "target", "rear")] == ["bow", "core", "stern"]
    with pytest.raises(GeometryError, match="outside hull bounds"):
        path_from_point(hull, [0, 0, 10], "bow")
    with pytest.raises(GeometryError, match="Unknown approach"):
        target_points(hull["sockets"]["target"], "diagonal")


def test_component_fit_uses_audited_type_overhang_and_rotation_rules(geometry):
    slot = socket()
    component = geometry["components"]["part"]
    assert fits_component(slot, component)
    assert not fits_component(slot, {**component, "type": 2})
    assert not fits_component(slot, {**component, "interior_overhang": 1})
    assert fits_component({**slot, "interior_overhang": 3}, {**component, "interior_overhang": 1})
    slot["size"] = [1, 2, 3]
    component["size"] = [3, 2, 1]
    assert not fits_component(slot, component)
    assert fits_component(slot, {**component, "rotate_to_fit": 1})
    assert not fits_component(slot, {**component, "size": [3, 3, 1], "rotate_to_fit": 1})
    # AnyAxis really compares squared diagonals: the long side need not fit
    # any axis individually. Replacing this with a permutation test is wrong.
    assert fits_component({**slot, "size": [3, 3, 3]}, {**component, "size": [4, 1, 1], "rotate_to_fit": 2})
    assert not fits_component(slot, {**component, "rotate_to_fit": 99})

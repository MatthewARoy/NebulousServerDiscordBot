"""Synthetic-only extraction tests; no proprietary bundles or UnityPy required."""

import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    "build_fleet_geometry", Path(__file__).resolve().parents[2] / "scripts" / "build_fleet_geometry.py")
export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export)


def test_socket_uses_runtime_dimensions_not_placeholder_collider_size():
    result = export.socket_geometry(export.IDENTITY, {"_size": dict(x=8, y=2, z=4)},
                                    {"m_Center": dict(x=1, y=0, z=0), "m_Size": dict(x=999, y=999, z=999)})
    assert result["center"] == [1, 0, 0]
    assert result["half_extents"] == [1, .25, .5]


def test_parent_rotation_scale_and_child_offset_are_composed():
    quarter_turn = (0, 0, math.sqrt(.5), math.sqrt(.5))
    parent = export.transform_matrix((10, 20, 30), quarter_turn, (2, 2, 2))
    child = export.transform_matrix((3, 0, 0), (0, 0, 0, 1), (1, 1, 1))
    result = export.box_geometry(export._multiply(parent, child), (0, 0, 0), (2, 4, 6))
    assert result["center"] == pytest.approx([10, 26, 30])
    assert result["half_extents"] == pytest.approx([2, 4, 6])
    assert result["rotation"] == pytest.approx(quarter_turn)


def test_sheared_boxes_are_rejected_instead_of_approximated_as_exact():
    parent = export.transform_matrix((0, 0, 0), (0, 0, 0, 1), (2, 1, 1))
    child = export.transform_matrix((0, 0, 0), (0, 0, math.sin(math.pi/8), math.cos(math.pi/8)), (1, 1, 1))
    with pytest.raises(ValueError, match="Sheared"):
        export.box_geometry(export._multiply(parent, child), (0, 0, 0), (1, 1, 1))


def test_mirrored_box_preserves_extents_with_proper_rotation():
    matrix = export.transform_matrix((1, 2, 3), (0, 0, 0, 1), (-2, 3, 4))
    result = export.box_geometry(matrix, (1, 0, 0), (2, 4, 6))
    assert result["center"] == [-1, 2, 3]
    assert result["half_extents"] == [2, 6, 12]
    assert sum(x*x for x in result["rotation"]) == pytest.approx(1)


def test_content_identity_is_deterministic_and_changes_with_geometry():
    first = export.stamp_geometry({"hulls": {"h": {"center": [1., 0., 0.]}}, "schema_version": 1})
    reordered = export.stamp_geometry({"schema_version": 1, "hulls": first["hulls"], "geometry_id": "stale"})
    changed = export.stamp_geometry({"hulls": {"h": {"center": [1.01, 0., 0.]}}, "schema_version": 1})
    assert first == reordered
    assert first["geometry_id"] != changed["geometry_id"]


def test_nonfinite_values_cannot_enter_the_cache():
    with pytest.raises(ValueError, match="Non-finite"):
        export.stamp_geometry({"half_extents": [float("nan"), 1, 1]})


def test_capsule_bounds_are_conservative_and_explicitly_inexact():
    class Capsule:
        type = type("Kind", (), {"name": "CapsuleCollider"})

        def read_typetree(self):
            return {"m_Radius": 1, "m_Height": 6, "m_Direction": 1, "m_Center": dict(x=0, y=0, z=0)}

    result = export._collider_geometry(Capsule(), export.transform_matrix((0, 0, 0), (0, 0, 0, 1), (3, 1, 2)))
    assert not result["exact"]
    assert result["half_extents"] == [9, 9, 9]


def test_sampling_bounds_include_protruding_socket_boxes():
    result = export.enclosing_bounds([
        {"center": [0, 0, 0], "half_extents": [1, 1, 1], "rotation": [0, 0, 0, 1]},
        {"center": [3, 0, 0], "half_extents": [1, 2, 1], "rotation": [0, 0, 0, 1]},
    ])
    assert result == {"center": [1.5, 0, 0], "half_extents": [2.5, 2, 1]}


def test_changed_bundles_cannot_be_labelled_as_the_audited_build(tmp_path, monkeypatch):
    for name in export.BUNDLES:
        (tmp_path / name).write_bytes(b"different installed build")
    monkeypatch.setitem(sys.modules, "UnityPy", SimpleNamespace(__version__="1.25.3"))
    with pytest.raises(ValueError, match="differ from the audited build"):
        export.build(tmp_path)

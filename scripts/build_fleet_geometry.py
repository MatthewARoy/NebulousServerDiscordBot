"""Build a PRIVATE, optional fleet-geometry cache from an installed stock game.

Requires UnityPy==1.25.3 only on the developer machine. Runtime bot dependencies
do not include UnityPy. Reads embedded bundle type trees, never launches/writes
the game, and exports no mesh data. Keep the result in ignored staging/; do not
redistribute the generated catalog in the public repository.

Geometry is in hull-local world units (1 wu = 10 m), quaternion xyzw. Socket
boxes use HullSocket.Awake's runtime size, integer socket dimensions * .25 wu,
NOT the placeholder prefab BoxCollider size. Non-socket damage colliders are
retained: exact boxes, or conservative bounds explicitly marked inexact.
This dataset establishes conditional collider geometry, not penetration,
attack coverage, combat survival, current health or ongoing function.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


GAME_VERSION = "0.6.2.6-public-steam25104609"
BUNDLES = ("stock", "stock-f1", "stock-f2")
# Read from the audited public build (Steam appmanifest buildid 25104609).
# A changed bundle requires a fresh mechanics/data audit, not a relabelled cache.
EXPECTED_BUNDLE_HASHES = {
    "stock": "f0eb47b761e73fa39723c6df481b8a59774b3286fc0a15d3274a0cc786b6c521",
    "stock-f1": "3cfeb699fe132b5588d0597c0e47979e2553dc35661f06a349f4e9ccafb04365",
    "stock-f2": "61e11598c74ce51d4c7f2d8f35e7ea5200799ca852d4b1e327e20e8a72230093",
}
STAT_NAMES = {"component-dr", "hull-componentdr"}
IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))


def _vector(value, axes="xyz"):
    result = [float(value[axis]) for axis in axes]
    if not all(math.isfinite(x) for x in result):
        raise ValueError("Non-finite geometry")
    return result


def _multiply(a, b):
    return tuple(tuple(sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)) for r in range(4))


def transform_matrix(position, rotation, scale):
    """Unity TRS, preserving parent scale when composing an entire hierarchy."""
    x, y, z, w = rotation
    norm = math.sqrt(sum(v * v for v in rotation))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError("Invalid quaternion")
    x, y, z, w = (v / norm for v in (x, y, z, w))
    rotation_rows = ((1 - 2*y*y - 2*z*z, 2*x*y - 2*w*z, 2*x*z + 2*w*y),
                     (2*x*y + 2*w*z, 1 - 2*x*x - 2*z*z, 2*y*z - 2*w*x),
                     (2*x*z - 2*w*y, 2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y))
    return tuple(tuple(rotation_rows[r][c] * scale[c] for c in range(3)) + (position[r],)
                 for r in range(3)) + ((0., 0., 0., 1.),)


def _quaternion(rows):
    # Stable matrix -> quaternion, with a canonical sign for deterministic output.
    trace = sum(rows[i][i] for i in range(3))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = [(rows[2][1] - rows[1][2]) / s, (rows[0][2] - rows[2][0]) / s,
             (rows[1][0] - rows[0][1]) / s, s / 4]
    else:
        i = max(range(3), key=lambda a: rows[a][a])
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1 + rows[i][i] - rows[j][j] - rows[k][k]) * 2
        q = [0., 0., 0., (rows[k][j] - rows[j][k]) / s]
        q[i], q[j], q[k] = s / 4, (rows[j][i] + rows[i][j]) / s, (rows[k][i] + rows[i][k]) / s
    if q[3] < 0:
        q = [-v for v in q]
    return q


def box_geometry(matrix, center, size):
    """Transform an OBB; reject shear instead of silently substituting an AABB."""
    columns = [[matrix[r][c] for r in range(3)] for c in range(3)]
    lengths = [math.sqrt(sum(v*v for v in column)) for column in columns]
    if min(lengths) < 1e-10 or min(size) <= 0:
        raise ValueError("Degenerate collider")
    axes = [[v / length for v in column] for column, length in zip(columns, lengths, strict=True)]
    if any(abs(sum(axes[a][r] * axes[b][r] for r in range(3))) > 1e-6
           for a, b in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("Sheared collider hierarchy is unsupported")
    # Mirror transforms do not change box shape; flip one axis to obtain a rotation.
    cross = [axes[0][1]*axes[1][2]-axes[0][2]*axes[1][1],
             axes[0][2]*axes[1][0]-axes[0][0]*axes[1][2],
             axes[0][0]*axes[1][1]-axes[0][1]*axes[1][0]]
    if sum(cross[i]*axes[2][i] for i in range(3)) < 0:
        axes[2] = [-v for v in axes[2]]
    return {"center": [sum(matrix[r][c] * center[c] for c in range(3)) + matrix[r][3] for r in range(3)],
            "rotation": _quaternion([[axes[c][r] for c in range(3)] for r in range(3)]),
            "half_extents": [size[i] * lengths[i] / 2 for i in range(3)]}


def socket_geometry(matrix, socket, collider):
    size = _vector(socket["_size"])
    return box_geometry(matrix, _vector(collider["m_Center"]), [v * .25 for v in size])


def enclosing_bounds(boxes):
    """AABB of OBBs for sampling only; this is not a hull/armor surface."""
    low, high = [math.inf] * 3, [-math.inf] * 3
    for box in boxes:
        rotation = transform_matrix((0, 0, 0), box["rotation"], (1, 1, 1))
        for axis in range(3):
            radius = sum(abs(rotation[axis][c]) * box["half_extents"][c] for c in range(3))
            low[axis] = min(low[axis], box["center"][axis] - radius)
            high[axis] = max(high[axis], box["center"][axis] + radius)
    return {"center": [(a+b)/2 for a, b in zip(low, high, strict=True)],
            "half_extents": [(b-a)/2 for a, b in zip(low, high, strict=True)]}


def _canonical(value):
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite exported number")
        return 0. if abs(value) < 1e-10 else round(value, 9)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def stamp_geometry(dataset):
    result = _canonical({k: v for k, v in dataset.items() if k != "geometry_id"})
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    result["geometry_id"] = hashlib.sha256(payload).hexdigest()
    return result


def _stat_modifiers(fields):
    return [{"stat": item["_statName"], "literal": item["_literal"], "modifier": item["_modifier"],
             "permanent": bool(item["_permanent"])}
            for value in fields.values() if isinstance(value, list) for item in value
            if isinstance(item, dict) and item.get("_statName") in STAT_NAMES]


def _walk(root):
    """Yield hierarchy nodes and hull-local matrices; ignore root world placement."""
    def visit(obj, parent_matrix, path, active, is_root=False):
        go = obj.read()
        components = [c.component.deref() for c in go.m_Component]
        transform = next(c for c in components if c.type.name in ("Transform", "RectTransform"))
        tr = transform.read_typetree()
        matrix = parent_matrix if is_root else _multiply(parent_matrix, transform_matrix(
            _vector(tr["m_LocalPosition"]), _vector(tr["m_LocalRotation"], "xyzw"), _vector(tr["m_LocalScale"])))
        path = path + "/" + go.m_Name if path else go.m_Name
        active = active and bool(go.m_IsActive)
        yield {"object": obj, "go": go, "components": components, "matrix": matrix,
               "path": path, "active": active}
        for child in transform.read().m_Children:
            yield from visit(child.read().m_GameObject.deref(), matrix, path, active)
    yield from visit(root, IDENTITY, "", True, is_root=True)


def _mono(node):
    return [(obj, obj.read_typetree()) for obj in node["components"] if obj.type.name == "MonoBehaviour"]


def _script(obj):
    script = obj.read(check_read=False).m_Script.read()
    return f"{script.m_Namespace}.{script.m_ClassName}"


def _collider_geometry(obj, matrix, override_size=None):
    tree = obj.read_typetree()
    shape = obj.type.name
    if shape == "BoxCollider":
        size = override_size or _vector(tree["m_Size"])
        exact = True
    elif shape in ("CapsuleCollider", "SphereCollider"):
        size = [2 * tree["m_Radius"]] * 3
        if shape == "CapsuleCollider":
            size[tree["m_Direction"]] = max(tree["m_Height"], size[tree["m_Direction"]])
        exact = False
    else:
        raise ValueError(f"Unbounded unsupported {shape}")
    geometry = box_geometry(matrix, _vector(tree["m_Center"]), size)
    if not exact:
        # Broadphase only: a bounding cube around a circumscribed sphere stays
        # conservative under nonuniform scale, including Unity capsule scaling.
        largest_scale = max(math.sqrt(sum(matrix[r][c] ** 2 for r in range(3))) for c in range(3))
        geometry["half_extents"] = [max(size) * largest_scale / 2] * 3
    return {**geometry, "shape": shape.removesuffix("Collider").lower(), "exact": exact}


def _hull(root):
    nodes = list(_walk(root))
    obj, fields = next((obj, f) for obj, f in _mono(nodes[0]) if "_hullClassification" in f)
    if "_bows" in fields:
        return {"unsupported": ["Modular segment transforms require the saved hull configuration."],
                "sockets": {}, "other_colliders": []}
    sockets, other, unsupported = {}, [], []
    bounds = None
    for node in nodes:
        scripts = _mono(node)
        socket = next((f for ob, f in scripts if _script(ob) == "Ships.HullSocket"), None)
        colliders = [ob for ob in node["components"] if ob.type.name.endswith("Collider")]
        if socket is not None:
            try:
                if not node["active"] or node["go"].m_Layer != 11:
                    raise ValueError("Inactive socket or unexpected damage layer")
                if len(colliders) != 1 or colliders[0].type.name != "BoxCollider":
                    raise ValueError("Socket must own one box collider")
                key = socket["_key"]
                if key in sockets:
                    raise ValueError("Duplicate socket identity")
                sockets[key] = {"name": node["go"].m_Name, "type": socket["_type"],
                                "size": [socket["_size"][a] for a in "xyz"],
                                "interior_overhang": socket["_interiorOverhangSpace"] & 63,
                                "layer": node["go"].m_Layer,
                                **socket_geometry(node["matrix"], socket, colliders[0].read_typetree())}
            except (KeyError, ValueError) as exc:
                unsupported.append(f"{node['path']}: {exc}")
            continue
        for index, collider in enumerate(colliders):
            if not node["active"] or not collider.read_typetree().get("m_Enabled"):
                continue
            if node["go"].m_Name == "Select" and collider.type.name == "BoxCollider":
                bounds = _collider_geometry(collider, node["matrix"])
            if node["go"].m_Layer != 11:
                continue
            part = next((f for ob, f in scripts if "_damageThreshold" in f), None)
            structure = any(_script(ob) == "Ships.HullStructure" for ob, _ in scripts)
            kind = "part" if part is not None else "structure" if structure else "unknown"
            try:
                geometry = _collider_geometry(collider, node["matrix"])
                entry = {"collider_id": f"{node['path']}#{index}", "recipient_id": node["path"], "kind": kind,
                         "layer": 11, **geometry}
                if part is not None:
                    entry.update(base_dt=part["_damageThreshold"], reinforced=bool(part["_reinforced"]))
                if kind == "unknown":
                    entry["exact"] = False
                other.append(entry)
            except (KeyError, ValueError) as exc:
                unsupported.append(f"{node['path']}: {exc}")
    if bounds is None:
        unsupported.append("Missing hull Select box bounds")
    base_dr = fields["_componentDR"]
    sampling_bounds = enclosing_bounds([bounds, *sockets.values()]) if bounds and sockets else bounds
    return {"sockets": sockets, "other_colliders": other, "bounds": sampling_bounds, "select_bounds": bounds,
            "min_component_dr": base_dr * .25, "max_component_dr": min(.5, max(-.5, base_dr)),
            "stat_modifiers": _stat_modifiers(fields), "faction": fields["_factionKey"],
            "sphere_query_complete": False,
            "sphere_query_unsupported": [
                "SphereOverlapComponents fills a 20-collider all-layer buffer before filtering damageable recipients; "
                "this socket cache cannot establish whether unexported hull/component colliders truncate that buffer."],
            "unsupported": unsupported}


def _component(root):
    nodes = list(_walk(root))
    _, fields = next((o, f) for o, f in _mono(nodes[0]) if "_pointCost" in f and "_damageThreshold" in f)
    unsupported = [f"{n['path']}: component adds a layer-11 collider"
                   for n in nodes if n["active"] and n["go"].m_Layer == 11
                   and any(o.type.name.endswith("Collider") and o.read_typetree().get("m_Enabled")
                           for o in n["components"])]
    return {"type": fields["_type"], "size": [fields["_size"][a] for a in "xyz"],
            "rotate_to_fit": fields["_rotateToFit"], "can_tile": bool(fields["_canTile"]),
            "interior_overhang": fields["_interiorOverhang"] & 63, "point_cost": fields["_pointCost"],
            "faction": fields["_factionKey"], "stat_modifiers": _stat_modifiers(fields),
            "crew_required": fields.get("_crewRequired", 0),
            "unsupported": unsupported}


def build(bundles):
    import UnityPy  # Developer-only extraction dependency; no import during bot operation/tests.
    if UnityPy.__version__ != "1.25.3":
        raise ValueError("Use the audited UnityPy==1.25.3 extraction dependency")
    paths = [bundles / name for name in BUNDLES]
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if source_hashes != EXPECTED_BUNDLE_HASHES:
        raise ValueError("Stock bundles differ from the audited build; re-audit before exporting geometry")
    env = UnityPy.load(*(str(path) for path in paths))
    container = {k.lower(): v for k, v in env.container.items()}
    result = {"schema_version": 1, "game_version": GAME_VERSION, "units": "world_units",
              "provenance": ["UnityPy 1.25.3 embedded type trees; stock bundle manifests select identities.",
                             "HullSocket.cs:195-204,255-260,282-287; box size=socket dimensions*0.25 wu; occupied/non-destroyed sockets active.",
                             "MunitionsHelpers.cs:139-146,172-185; layer 11 ray hits sorted by distance; collider duplicates retained.",
                             "ShipController.cs:5553-5580; exclude structural hits when nonstructural recipients exist. Structure is not an extra divisor.",
                             "PenetratingExplosiveDamager.cs:49; MunitionsHelpers.cs:190-205: HE uses a 20-collider ALL-LAYER overlap buffer before recipient filtering. This cache cannot certify sphere-query completeness.",
                             "BaseHull.cs:787-794; DR fill uses occupied socket count / all socket count, lerp over .2-.6 fill.",
                             "HullStructure.cs:10,31-37,122-140; structural recipient has no component DT.",
                             "Sampling bounds enclose Select and socket boxes; they are not an armor surface or a verified damage-ray entry point.",
                             "Utility/Sides.cs:7-15; overhang masks normalized to six defined bits (63), including serialized -1 values.",
                             "Prefab geometry, not a Unity raycast conformance test. Capsule/sphere bounds are inexact.",
                             "Generated data is private local cache; do not publish or redistribute."],
              "source_hashes": source_hashes,
              "hulls": {}, "components": {}, "excluded_hulls": {}}
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        asset = obj.read()
        if asset.m_Name != "manifest":
            continue
        xml = asset.m_Script if isinstance(asset.m_Script, str) else asset.m_Script.decode("utf-8")
        root = ET.fromstring(re.sub(r'xmlns(:\w+)?="[^"]+"', "", xml))
        base, namespace = root.findtext("BasePath"), root.findtext("Namespace")
        for category, export in (("Hulls", _hull), ("Components", _component)):
            section = root.find(category)
            if section is None:
                continue
            for entry in section.findall("Entry"):
                key = f"{namespace}/{entry.get('Name')}"
                address = f"{base}/{entry.get('Address')}".lower()
                record = export(container[address].deref())
                if category == "Hulls" and not record["sockets"]:
                    result["excluded_hulls"][key] = record["unsupported"]
                else:
                    result[category.lower()][key] = record
    return stamp_geometry(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--bundles", type=Path, required=True, help="Installed game's Assets/AssetBundles directory")
    parser.add_argument("--out", type=Path, default=Path("staging/fleet_geometry.json"), help="PRIVATE ignored local cache")
    args = parser.parse_args(argv)
    result = build(args.bundles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Private geometry {result['geometry_id']}: {len(result['hulls'])} hulls, {len(result['components'])} components -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

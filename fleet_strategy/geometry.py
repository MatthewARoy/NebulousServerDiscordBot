"""Bounded, deterministic stock-socket geometry for conditional damage assessment.

These boxes describe socket colliders in hull-local world units, not armor or
the hull surface. Axis samples are a sparse set of hypothetical internal paths;
neither an intersection nor an empty path establishes combat protection.
"""

import hashlib
import itertools
import json
import math
from pathlib import Path


MAX_GEOMETRY_BYTES = 8 * 1024 * 1024
MAX_HULLS = 128
MAX_SOCKETS = 32768
MAX_COMPONENTS = 4096
MAX_COORDINATE = 1_000_000
_EPSILON = 1e-9
DIRECTIONS = {
    "bow": (0.0, 0.0, -1.0),
    "stern": (0.0, 0.0, 1.0),
    "port": (1.0, 0.0, 0.0),
    "starboard": (-1.0, 0.0, 0.0),
    "top": (0.0, -1.0, 0.0),
    "bottom": (0.0, 1.0, 0.0),
}


class GeometryError(ValueError):
    """Geometry or a requested path is malformed or exceeds supported bounds."""


def _number(value):
    return type(value) in (int, float) and abs(value) <= MAX_COORDINATE and math.isfinite(value)


def _vector(value, count=3, *, positive=False, integer=False):
    return isinstance(value, (list, tuple)) and len(value) == count and all(
        _number(item) and (not positive or item > 0) and (not integer or type(item) is int)
        for item in value
    )


def _string(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1024


def _strings(value):
    return isinstance(value, list) and len(value) <= 256 and all(_string(item) for item in value)


def _json_problem(data):
    """Reject non-JSON data, excessive nesting, cycles and nonfinite metadata."""
    pending = [(data, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 32 or count > 500000:
            return "geometry exceeds nesting or node limits"
        if isinstance(value, dict):
            if any(not isinstance(key, str) or len(key) > 1024 for key in value):
                return "geometry object keys must be bounded strings"
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, str):
            if len(value) > 4096:
                return "geometry strings exceed the length limit"
        elif type(value) in (int, float):
            try:
                if not math.isfinite(value):
                    return "geometry contains a nonfinite number"
            except OverflowError:
                return "geometry contains an oversized number"
        elif value is not None and type(value) is not bool:
            return "geometry must contain only JSON values"
    return None


def _digest(data):
    try:
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise GeometryError("Cannot fingerprint a non-JSON snapshot.") from exc


def geometry_fingerprint(data):
    """Hash all geometry content except its self-referential geometry_id."""
    if not isinstance(data, dict):
        raise GeometryError("Geometry must be an object.")
    return _digest({key: value for key, value in data.items() if key != "geometry_id"})


def build_fingerprint(fleet):
    """Hash the entire parsed snapshot, including fit/configuration state.

    Callers must preserve all state they need invalidated in their snapshot.
    This cannot recover fields discarded by an upstream save-file reader.
    """
    return _digest(fleet)


def _box_problem(box, *, rotated=False):
    if not isinstance(box, dict) or not _vector(box.get("center")):
        return "box center must have three finite coordinates"
    if not _vector(box.get("half_extents"), positive=True):
        return "box half_extents must have three positive finite coordinates"
    if rotated:
        rotation = box.get("rotation")
        if not _vector(rotation, 4) or abs(sum(item * item for item in rotation) - 1) > 1e-5:
            return "socket rotation must be a normalized xyzw quaternion"
    return None


def _fitting_problem(record):
    if not isinstance(record, dict) or type(record.get("type")) is not int or record["type"] not in (0, 1, 2):
        return "fitting type must be 0, 1 or 2"
    if not _vector(record.get("size"), positive=True, integer=True):
        return "fitting size must have three positive integers"
    overhang = record.get("interior_overhang")
    if type(overhang) is not int or not 0 <= overhang <= 2**31 - 1:
        return "fitting interior_overhang must be a nonnegative bit mask"
    return None


def geometry_problem(data):
    """Return a diagnostic for unsupported geometry; never infer missing data."""
    problem = _json_problem(data)
    if problem:
        return problem
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        return "unsupported geometry schema_version; expected 1"
    if not _string(data.get("game_version")) or not _strings(data.get("provenance")) or not data["provenance"]:
        return "geometry needs a game_version and nonempty provenance"
    identity = data.get("geometry_id")
    if not isinstance(identity, str) or len(identity) != 64 or any(ch not in "0123456789abcdef" for ch in identity):
        return "geometry_id must be a lowercase SHA-256 content fingerprint"
    hulls, components = data.get("hulls"), data.get("components")
    if not isinstance(hulls, dict) or not hulls or len(hulls) > MAX_HULLS:
        return "geometry hulls must be a nonempty bounded object"
    if not isinstance(components, dict) or not components or len(components) > MAX_COMPONENTS:
        return "geometry components must be a nonempty bounded object"
    total_sockets = 0
    for hull_id, hull in hulls.items():
        if not _string(hull_id) or not isinstance(hull, dict):
            return "invalid geometry hull record"
        sockets = hull.get("sockets")
        if not isinstance(sockets, dict) or not sockets:
            return f"{hull_id}: sockets must be a nonempty object"
        total_sockets += len(sockets)
        if total_sockets > MAX_SOCKETS:
            return "geometry exceeds the socket count limit"
        problem = _box_problem(hull.get("bounds"))
        if problem:
            return f"{hull_id}: {problem}"
        if not _strings(hull.get("unsupported")):
            return f"{hull_id}: unsupported must be a string array"
        minimum, maximum = hull.get("min_component_dr"), hull.get("max_component_dr")
        if not _number(minimum) or not _number(maximum) or not 0 <= minimum <= maximum <= 1:
            return f"{hull_id}: component DR bounds must satisfy 0 <= min <= max <= 1"
        for key, socket in sockets.items():
            if not _string(key):
                return f"{hull_id}: invalid socket key"
            problem = _fitting_problem(socket) or _box_problem(socket, rotated=True)
            if problem:
                return f"{hull_id}/{key}: {problem}"
            if type(socket.get("layer")) is not int or socket["layer"] != 11:
                return f"{hull_id}/{key}: expected component-collider layer 11"
            # Every rotated box must fit in the declared broad-phase bounds.
            axes = _axes(socket["rotation"])
            bounds = hull["bounds"]
            for axis in range(3):
                radius = sum(abs(axes[local][axis]) * socket["half_extents"][local] for local in range(3))
                if abs(socket["center"][axis] - bounds["center"][axis]) + radius > bounds["half_extents"][axis] + 1e-6:
                    return f"{hull_id}/{key}: socket extends outside declared hull bounds"
        colliders = hull.get("other_colliders", [])
        if not isinstance(colliders, list):
            return f"{hull_id}: other_colliders must be an array"
        total_sockets += len(colliders)
        if total_sockets > MAX_SOCKETS:
            return "geometry exceeds the collider count limit"
        collider_ids = set()
        for collider in colliders:
            problem = _box_problem(collider, rotated=True)
            if problem:
                return f"{hull_id}: {problem}"
            collider_id = collider.get("collider_id")
            if not _string(collider_id) or collider_id in collider_ids or collider_id in sockets:
                return f"{hull_id}: other collider IDs must be nonempty and unique"
            collider_ids.add(collider_id)
            if not _string(collider.get("recipient_id")) or collider.get("kind") not in ("structure", "part", "unknown"):
                return f"{hull_id}: other collider has invalid recipient identity or kind"
            if collider.get("shape") not in ("box", "capsule") or type(collider.get("exact")) is not bool:
                return f"{hull_id}: other collider has invalid shape or exact flag"
            threshold = collider.get("base_dt")
            if threshold is not None and (not _number(threshold) or threshold < 0):
                return f"{hull_id}: other collider DT must be nonnegative finite or null"
            reinforced = collider.get("reinforced")
            if reinforced is not None and type(reinforced) is not bool:
                return f"{hull_id}: other collider reinforcement must be boolean or null"
            if collider["shape"] != "box" and collider["exact"]:
                return f"{hull_id}: a non-box collider cannot be exact in the OBB kernel"
    for component_id, component in components.items():
        if not _string(component_id):
            return "invalid geometry component key"
        problem = _fitting_problem(component)
        if problem:
            return f"{component_id}: {problem}"
        if type(component.get("rotate_to_fit")) is not int or component["rotate_to_fit"] not in (0, 1, 2):
            return f"{component_id}: unsupported rotate_to_fit enum"
        if type(component.get("can_tile")) is not bool:
            return f"{component_id}: can_tile must be boolean"
        if not _number(component.get("point_cost")) or component["point_cost"] < 0:
            return f"{component_id}: point_cost must be nonnegative and finite"
        if not isinstance(component.get("faction"), str) or len(component["faction"]) > 1024:
            return f"{component_id}: faction must be a string"
    if identity != geometry_fingerprint(data):
        return "geometry_id does not match its content"
    return None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GeometryError(f"Duplicate geometry object key: {key}.")
        result[key] = value
    return result


def _reject_constant(value):
    raise GeometryError(f"Nonfinite geometry number: {value}.")


def load_geometry(path):
    """Read at most 8 MiB of UTF-8 JSON and validate its schema and fingerprint."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_GEOMETRY_BYTES + 1)
        if len(raw) > MAX_GEOMETRY_BYTES:
            raise GeometryError("Geometry exceeds the 8 MiB size limit.")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except GeometryError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise GeometryError(f"Cannot read geometry: {exc}.") from exc
    problem = geometry_problem(data)
    if problem:
        raise GeometryError(problem)
    return data


def _axes(quaternion):
    norm = math.sqrt(sum(item * item for item in quaternion))
    x, y, z, w = (item / norm for item in quaternion)
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)),
        (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)),
        (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)),
    )


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right, strict=True))


def _occupied(sockets, occupied_keys):
    if not isinstance(sockets, dict) or len(sockets) > MAX_SOCKETS:
        raise GeometryError("Query sockets must be a bounded object.")
    if isinstance(occupied_keys, (str, bytes)):
        raise GeometryError("Occupied socket keys must be a collection of keys.")
    try:
        keys = list(itertools.islice(occupied_keys, MAX_SOCKETS + 1))
    except TypeError as exc:
        raise GeometryError("Occupied socket keys must be iterable.") from exc
    if len(keys) > MAX_SOCKETS or any(not _string(key) for key in keys) or len(set(keys)) != len(keys):
        raise GeometryError("Occupied socket keys must be bounded and unique.")
    if any(key not in sockets for key in keys):
        raise GeometryError("Occupied socket has no geometry.")
    return keys


def ray_hits(origin, direction, sockets, occupied_keys, max_distance):
    """Intersect a finite ray with occupied socket OBBs, in world-unit order.

    Direction is normalized here. A tangent/face-only contact has no interior
    interval and is conservatively excluded. Distances start at the supplied
    origin. Following Unity's raycast convention, a collider containing the
    origin is excluded, rather than counted as an entry at distance zero.
    """
    if not _vector(origin) or not _vector(direction) or math.hypot(*direction) <= _EPSILON:
        raise GeometryError("Ray origin and nonzero direction must have three finite coordinates.")
    if not _number(max_distance) or max_distance <= 0:
        raise GeometryError("Ray max_distance must be positive and finite.")
    keys = _occupied(sockets, occupied_keys)
    norm = math.hypot(*direction)
    unit = tuple(item / norm for item in direction)
    result = []
    for key in keys:
        socket = sockets[key]
        problem = _box_problem(socket, rotated=True)
        if problem:
            raise GeometryError(problem)
        relative = tuple(origin[i] - socket["center"][i] for i in range(3))
        axes = _axes(socket["rotation"])
        if all(abs(_dot(relative, axis)) < extent - _EPSILON
               for axis, extent in zip(axes, socket["half_extents"], strict=True)):
            continue
        enter, exit_distance = 0.0, float(max_distance)
        for axis, extent in zip(axes, socket["half_extents"], strict=True):
            position, speed = _dot(relative, axis), _dot(unit, axis)
            if abs(speed) <= _EPSILON:
                if abs(position) >= extent - _EPSILON:
                    exit_distance = -1.0
                    break
                continue
            first, last = sorted(((-extent - position) / speed, (extent - position) / speed))
            enter, exit_distance = max(enter, first), min(exit_distance, last)
            if exit_distance - enter <= _EPSILON:
                break
        if exit_distance - enter > _EPSILON:
            result.append({"socket_key": key, "enter": enter, "exit": exit_distance})
    return sorted(result, key=lambda hit: (hit["enter"], hit["exit"], hit["socket_key"]))


def sphere_hits(center, radius, sockets, occupied_keys):
    """Exact sphere-versus-OBB query, excluding tangent-only contacts.

    The caller supplies the hypothetical detonation point and radius; this
    helper makes no assertion that a munition reaches that point. Non-box
    collider records must be handled as uncertain by their caller.
    """
    if not _vector(center) or not _number(radius) or radius <= 0:
        raise GeometryError("Sphere center and positive radius must be finite.")
    keys = _occupied(sockets, occupied_keys)
    result = []
    for key in keys:
        socket = sockets[key]
        problem = _box_problem(socket, rotated=True)
        if problem:
            raise GeometryError(problem)
        relative = tuple(center[i] - socket["center"][i] for i in range(3))
        outside = [max(0, abs(_dot(relative, axis)) - extent)
                   for axis, extent in zip(_axes(socket["rotation"]), socket["half_extents"], strict=True)]
        if math.hypot(*outside) < radius - _EPSILON:
            result.append(key)
    return sorted(result)


def _direction(direction_name):
    if direction_name not in DIRECTIONS:
        raise GeometryError("Unknown approach direction.")
    return DIRECTIONS[direction_name]


def target_points(socket, direction_name):
    """Center plus four half-radius offsets on the two most transverse local axes."""
    direction = _direction(direction_name)
    problem = _box_problem(socket, rotated=True)
    if problem:
        raise GeometryError(problem)
    axes = _axes(socket["rotation"])
    transverse = sorted(range(3), key=lambda i: (abs(_dot(axes[i], direction)), i))[:2]
    points = [list(socket["center"])]
    for axis in transverse:
        for sign in (-1, 1):
            points.append([
                socket["center"][i] + sign * 0.5 * socket["half_extents"][axis] * axes[axis][i]
                for i in range(3)
            ])
    return points


def path_from_point(hull, target_point, direction_name):
    """Return the complete bounds chord through a point; this is not armor entry."""
    direction = _direction(direction_name)
    if not isinstance(hull, dict) or _box_problem(hull.get("bounds")) or not _vector(target_point):
        raise GeometryError("Path needs finite hull bounds and a finite target point.")
    bounds = hull["bounds"]
    if any(abs(target_point[i] - bounds["center"][i]) > bounds["half_extents"][i] + _EPSILON for i in range(3)):
        raise GeometryError("Target point lies outside hull bounds.")
    axis = next(i for i, value in enumerate(direction) if value)
    origin = list(target_point)
    origin[axis] = bounds["center"][axis] - direction[axis] * bounds["half_extents"][axis]
    return {"origin": origin, "direction": list(direction), "length": 2 * bounds["half_extents"][axis]}


def sample_paths(hull, occupied_keys, target_key, direction_name):
    """Five complete-chord samples, including all occupied intersections.

    Callers must apply finite threat depths and decline ambiguous/overlapping
    recipient interpretations. This function does not turn these paths into a
    claim about penetration, armor entry or continuous angular coverage.
    """
    if not isinstance(hull, dict) or target_key not in hull.get("sockets", {}):
        raise GeometryError("Target socket has no geometry.")
    keys = _occupied(hull["sockets"], occupied_keys)
    result = []
    for index, point in enumerate(target_points(hull["sockets"][target_key], direction_name)):
        path = path_from_point(hull, point, direction_name)
        hits = ray_hits(path["origin"], path["direction"], hull["sockets"], keys, path["length"])
        result.append({"sample_index": index, "target_point": point, **path,
                       "socket_keys": [hit["socket_key"] for hit in hits], "hits": hits})
    return result


def region_for_socket(hull, socket_key):
    """Geometric longitudinal thirds only: positive local Z is the bow."""
    if not isinstance(hull, dict) or socket_key not in hull.get("sockets", {}) or _box_problem(hull.get("bounds")):
        raise GeometryError("Region needs a known socket and finite hull bounds.")
    center = hull["sockets"][socket_key].get("center")
    if not _vector(center):
        raise GeometryError("Region needs a finite socket center.")
    offset = center[2] - hull["bounds"]["center"][2]
    third = hull["bounds"]["half_extents"][2] / 3
    return "bow" if offset > third else "stern" if offset < -third else "core"


def fits_component(socket, component):
    """Reproduce the audited type, overhang and TestSocketFit dimension gates.

    RotateAxis: None=0, UpOnly=1, AnyAxis=2. The game's AnyAxis comparison is
    squared diagonal length, not a search over dimension permutations. This
    predicate does not establish faction eligibility, availability, point
    budget, tiling count or editor-specific constraints.
    """
    if _fitting_problem(socket) or _fitting_problem(component):
        return False
    mode = component.get("rotate_to_fit")
    if type(mode) is not int or mode not in (0, 1, 2) or component["type"] != socket["type"]:
        return False
    overhang = component["interior_overhang"]
    if socket["interior_overhang"] & overhang != overhang:
        return False
    x, y, z = component["size"]
    sx, sy, sz = socket["size"]
    if mode == 2:
        return x * x + y * y + z * z <= sx * sx + sy * sy + sz * sz
    if mode == 1:
        return y <= sy and ((x <= sx and z <= sz) or (x <= sz and z <= sx))
    return x <= sx and y <= sy and z <= sz

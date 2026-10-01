"""Pinned stock packet arithmetic, conditional on a caller-selected hit collection.

This module does not raycast, reconstruct a hull, or simulate a battle. A socket
selection is an assumption about recipients, never evidence of a physical stack.
"""

import copy
import math

from .parser import FleetInputError, MAX_ID_LENGTH

MAX_STACK_PARTS = 64
_LIMITATIONS = [
    "The selected sockets are an assumed hit collection, not a verified nose stack. Save order and proximity do not establish shared hits.",
    "All selected parts are assumed present and not destroyed; no unselected part is included in the divisor or hit order.",
    "DT is a destruction gate, not damage immunity: packets can exhaust HP and disable functions even when they do not exceed DT.",
    "Exceeding DT only permits destruction when the HP gate also passes; reinforced parts must already have zero committed HP.",
    "No armor penetration, impact direction, hit probability, repeated-ray intersections, overpenetration, repair timing, critical effects or combat survival is predicted.",
    "DR is an explicit user assumption, not calculated from the save. Live hull modifiers and current component stats have not been measured.",
    "Arithmetic uses Python numbers, not a frame-accurate Unity float simulation; near-boundary results require in-game confirmation.",
]


def _number(value, label, *, maximum=None):
    if type(value) not in (int, float):
        raise FleetInputError(f"{label} must be a finite number.")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (maximum is not None and value > maximum):
        suffix = f" between 0 and {maximum}" if maximum is not None else " at least zero"
        raise FleetInputError(f"{label} must be finite and{suffix}.")
    return value


def destruction_gate(packet, threshold, *, current_health, pending_damage=0, reinforced=False):
    """Explain HullPart.DoDamage for one part before its damage frame commits.

    pending_damage is earlier damage in the same frame. It affects resulting HP,
    not the reinforced committed-health gate, and is not summed for the DT test.
    This helper deliberately does not model function state, repairs, or crits.
    """
    for name, value in (("packet", packet), ("threshold", threshold),
                        ("current_health", current_health), ("pending_damage", pending_damage)):
        _number(value, name)
    if type(reinforced) is not bool:
        raise FleetInputError("reinforced must be a boolean.")
    total = _number(packet + pending_damage, "frame damage")
    resulting_health = max(0, current_health - total)
    exceeds = packet > threshold
    return {
        "resulting_health": resulting_health,
        "threshold_exceeded": exceeds,
        "destroyed": resulting_health == 0 and exceeds and (not reinforced or current_health == 0),
    }


def validate_damage_model(model):
    """Fail closed on missing/partial mechanics rather than inventing defaults."""
    if not isinstance(model, dict) or model.get("schema_version") != 1:
        return "Damage model is missing or has an unsupported schema."
    if not isinstance(model.get("game_version"), str) or not model["game_version"]:
        return "Damage model has no pinned game version."
    for field in ("evidence", "limitations"):
        if not isinstance(model.get(field), list) or not model[field] or any(
            not isinstance(item, str) or not item for item in model[field]
        ):
            return f"Damage model {field} is missing or malformed."
    for field in ("components", "threats"):
        rows = model.get(field)
        if not isinstance(rows, list) or not rows or len(rows) > 512:
            return f"Damage model {field} is missing or malformed."
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key]
                                               for key in ("id", "source", "source_sha256")):
                return f"Damage model {field} lacks identity or provenance."
            if row["id"] in seen:
                return f"Damage model {field} contains duplicate IDs."
            seen.add(row["id"])
            if len(row["source_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["source_sha256"]):
                return f"Damage model {field} has an invalid source hash."
            try:
                if field == "components":
                    _number(row.get("threshold"), "threshold", maximum=1000000)
                    _number(row.get("max_health"), "max_health", maximum=1000000)
                    if type(row.get("reinforced")) is not bool:
                        return "Damage component reinforced flag is missing."
                else:
                    _number(row.get("packet_damage"), "packet_damage", maximum=1000000)
                    if row["packet_damage"] <= 0 or not isinstance(row.get("distribution"), str) or row["distribution"] not in {"even", "first", "falloff"}:
                        return "Damage profile has an unsupported distribution or packet."
                    if type(row.get("ignores_dr")) is not bool or any(
                        not isinstance(row.get(key), str) or not row[key] for key in ("label", "assumption")
                    ):
                        return "Damage profile lacks its DR policy or assumptions."
                    if row["distribution"] == "falloff":
                        _number(row.get("falloff"), "falloff", maximum=1)
                        if row["falloff"] <= 0:
                            return "Damage profile falloff must be positive."
                    if "geometry_mode" in row:
                        mode = row["geometry_mode"]
                        if mode not in ("ray", "explosion"):
                            return "Damage profile has an unsupported geometry mode."
                        field = "geometry_distance" if mode == "ray" else "geometry_radius"
                        _number(row.get(field), field, maximum=100)
                        if row[field] <= 0 or (mode == "explosion" and row["distribution"] != "even"):
                            return "Damage profile has invalid geometry parameters."
            except FleetInputError as exc:
                return str(exc)
    return None


def _model_problem(bundle):
    if not isinstance(bundle, dict):
        return "Damage knowledge bundle is unavailable."
    problem = validate_damage_model(bundle.get("damage_model"))
    if problem:
        return problem
    if bundle.get("catalog_version") != bundle["damage_model"]["game_version"]:
        return "Damage model and identity catalog versions do not match; no threshold conclusion is available."
    catalog = bundle.get("catalog")
    if not isinstance(catalog, dict) or any(not isinstance(catalog.get(key), dict) for key in ("hulls", "components")):
        return "Damage assessment requires a usable hull and component identity catalog."
    return None


def damage_inventory(fleet, bundle):
    """List known reinforced fittings for selection; never group them by location."""
    if _model_problem(bundle):
        return []
    known = {row["id"]: row for row in bundle["damage_model"]["components"] if row["reinforced"]}
    result = []
    for ship in fleet.get("ships", []):
        if ship.get("hull") not in bundle["catalog"]["hulls"] or any(
            socket.get("component") and socket["component"] not in bundle["catalog"]["components"]
            for socket in ship.get("sockets", [])
        ):
            continue
        sockets = [
            {"key": socket["key"], "component": socket["component"],
             "threshold": known[socket["component"]]["threshold"]}
            for socket in ship.get("sockets", [])
            if socket.get("key") and socket.get("component") in known
        ]
        if sockets:
            result.append({"ship_key": ship["key"], "ship_name": ship["name"], "sockets": sockets})
    return result


def _selected_ship(fleet, ship_key, socket_keys):
    if not isinstance(ship_key, str) or not ship_key or len(ship_key) > MAX_ID_LENGTH:
        raise FleetInputError("Select a valid ship key for the damage scenario.")
    if not isinstance(socket_keys, list) or not 1 <= len(socket_keys) <= MAX_STACK_PARTS or any(
        not isinstance(key, str) or not key or len(key) > MAX_ID_LENGTH for key in socket_keys
    ):
        raise FleetInputError(f"Select 1 to {MAX_STACK_PARTS} nonempty socket keys.")
    if len(set(socket_keys)) != len(socket_keys):
        raise FleetInputError("Damage scenario contains duplicate socket keys.")
    if not isinstance(fleet, dict) or not isinstance(fleet.get("ships"), list):
        raise FleetInputError("Damage scenario requires a fleet snapshot.")
    ships = [ship for ship in fleet["ships"] if isinstance(ship, dict) and ship.get("key") == ship_key]
    if len(ships) != 1:
        raise FleetInputError("Damage scenario ship key is missing or ambiguous.")
    ship = ships[0]
    sockets = ship.get("sockets")
    if not isinstance(ship.get("hull"), str) or not isinstance(sockets, list) or any(
        not isinstance(socket, dict) or (socket.get("component") is not None and not isinstance(socket["component"], str))
        for socket in sockets
    ):
        raise FleetInputError("Damage scenario needs saved socket identities.")
    selected = []
    for key in socket_keys:
        matches = [socket for socket in sockets if socket.get("key") == key]
        if len(matches) != 1 or not matches[0].get("component"):
            raise FleetInputError(f"Selected socket {key} is missing, empty or ambiguous.")
        selected.append(matches[0])
    return ship, selected


def evaluate_stack(fleet, bundle, *, ship_key, socket_keys, threat_id, damage_reduction):
    """Compare per-recipient packets to DT under explicit stock/path assumptions.

    The caller supplies the full ordered hit collection of non-destroyed parts.
    A result below DT is conditional arithmetic only, never a combat verdict.
    """
    _number(damage_reduction, "damage reduction (DR)", maximum=0.9)
    if not isinstance(threat_id, str) or not threat_id or len(threat_id) > MAX_ID_LENGTH:
        raise FleetInputError("Select a damage threat profile ID.")
    ship, selected = _selected_ship(fleet, ship_key, socket_keys)
    result = {
        "status": "unknown", "title": "Unknown — no DT conclusion",
        "summary": "No supported conditional calculation is available.",
        "ship_key": ship_key, "ship_name": ship.get("name", ship_key),
        "socket_keys": list(socket_keys), "threat": {"id": threat_id, "label": threat_id},
        "damage_reduction": damage_reduction, "game_version": None,
        "bundle_id": bundle.get("bundle_id") if isinstance(bundle, dict) else None,
        "recipients": [], "assumptions": ["The user selected the hit collection and supplied DR."],
        "limitations": list(_LIMITATIONS), "evidence": [],
    }
    problem = _model_problem(bundle)
    if problem:
        result["limitations"].append(problem)
        return result
    model = bundle["damage_model"]
    result["game_version"] = model["game_version"]
    result["evidence"] = list(model["evidence"])
    result["limitations"].extend(model["limitations"])
    profiles = {row["id"]: row for row in model["threats"]}
    components = {row["id"]: row for row in model["components"]}
    if threat_id not in profiles:
        result["limitations"].append("Unknown or unsupported threat profile; available: " + ", ".join(profiles) + ".")
        return result
    profile = profiles[threat_id]
    result["threat"] = copy.deepcopy(profile)
    catalog = bundle["catalog"]
    if ship.get("hull") not in catalog["hulls"] or any(
        socket.get("component") and socket["component"] not in catalog["components"] for socket in ship["sockets"]
    ):
        result["limitations"].append("Unknown hull or modded component in this ship; stock mechanics applicability is not established.")
        return result
    if any(socket["component"] not in components for socket in selected):
        result["limitations"].append("One or more selected components lack audited DT data; the entire scenario is withheld.")
        return result
    mode = profile["distribution"]
    applied_dr = 0 if profile["ignores_dr"] else damage_reduction
    packets = distribute_packets(profile, len(selected), damage_reduction)
    result["applied_damage_reduction"] = applied_dr
    result["assumptions"] = [
        profile["assumption"],
        "Selected keys, in order: " + ", ".join(socket_keys) + ". All are assumed hit and not destroyed.",
        f"User-assumed hull DR: {damage_reduction:g}; applied DR: {applied_dr:g}. "
        + ("This stock profile ignores DR." if profile["ignores_dr"] else "DR is applied before distribution."),
        "Audited stock thresholds are used without live modifiers. Comparison assumes HP can already be exhausted.",
    ]
    result["evidence"].append(profile["source"] + " [SHA-256 " + profile["source_sha256"] + "]")
    for index, socket in enumerate(selected):
        part = components[socket["component"]]
        packet = packets[index]
        threshold = part["threshold"]
        result["recipients"].append({
            "socket_key": socket["key"], "component": socket["component"],
            "threshold": threshold, "reinforced": part["reinforced"],
            "packet": packet, "exceeds_threshold": packet > threshold,
            "margin": threshold - packet,
        })
        result["evidence"].append(part["source"] + " [SHA-256 " + part["source_sha256"] + "]")
    if mode == "even":
        # A weakest-recipient budget for THIS equal split, not a sum of DTs.
        result["shared_packet_budget_after_dr"] = len(selected) * min(row["threshold"] for row in result["recipients"])
    exceeded = any(row["exceeds_threshold"] for row in result["recipients"])
    result["status"] = "threshold-exceeded" if exceeded else "conditional-below-dt"
    result["title"] = "DT exceeded — destruction possible" if exceeded else "Within DT — assumed path only"
    result["summary"] = (
        "At least one recipient packet exceeds DT; this permits destruction only if the health gate also passes."
        if exceeded else
        "No recipient packet exceeds DT in this assumed hit collection. HP loss and disabled functions remain possible."
    )
    result["evidence"] = list(dict.fromkeys(result["evidence"]))
    return result


def distribute_packets(profile, count, damage_reduction):
    """Shared arithmetic for explicit and geometry-derived recipient collections.

    Callers validate the versioned profile and determine the actual recipients.
    No part health, structure fallback, geometry or threshold is inferred here.
    """
    if type(count) is not int or not 1 <= count <= 512:
        raise FleetInputError("Damage recipient count must be between 1 and 512.")
    _number(damage_reduction, "damage reduction", maximum=0.9)
    pool = profile["packet_damage"] * (1 if profile["ignores_dr"] else 1 - damage_reduction)
    if profile["distribution"] == "even":
        return [pool / count] * count
    if profile["distribution"] == "first":
        return [pool] + [0] * (count - 1)
    packets = []
    for _ in range(count):
        packet = pool * profile["falloff"]
        packets.append(packet)
        pool -= packet
    return packets

"""Bounded, conditional regional review and proposals over local stock geometry.

Five deterministic probes per fitted socket are a sampling scheme, not a proof
about every possible hit. Geometry data is installed separately from this code.
"""

import copy
import hashlib
import json
import math

from .damage import _model_problem, distribute_packets
from .geometry import (
    build_fingerprint, fits_component, geometry_problem, path_from_point,
    ray_hits, region_for_socket, sphere_hits, target_points,
)
from .parser import FleetInputError, MAX_ID_LENGTH, MAX_SHIPS, MAX_SOCKETS

DIRECTIONS = ("bow", "stern", "port", "starboard", "top", "bottom")
MAX_PROBES = 6000
MAX_CANDIDATES = 6
QUERY_CAPACITY = 20
ENGINE_VERSION = "stock-dt-samples-v1"
_LIMITATIONS = [
    "Five deterministic probes per part are conditional samples, not all possible paths or a survival probability.",
    "Ray entry is assumed at the enclosing box; HE explosions are assumed at sampled target points. Hull surface, armor entry and overpenetration are not solved.",
    "HE sphere queries require verified complete collider coverage, including the game's all-layer overlap buffer. Stock geometry currently cannot establish that coverage.",
    "Queries reaching the game's 20-collider buffer capacity are unknown, including structural hits before recipient filtering.",
    "All fitted components and hull parts are assumed not destroyed. Runtime damage, repairs, critical effects and structure-only fallback are not simulated.",
    "DT and DR use pinned stock data and socket occupancy, not a live measurement. HP loss and disabled functions remain possible within DT.",
    "A stack's supporting recipients can change after damage. Target results retain supporting-part uncertainty and do not certify combat immunity.",
    "Python arithmetic and ideal collider math do not reproduce Unity float/contact tolerances; near-boundary results require in-game confirmation.",
    "Proposals add an empty reinforced magazine only; confirm final cost, mass, resources and intended use in the editor. No fleet changes are applied.",
]


def _id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _source_id(source, field):
    value = source.get(field) if isinstance(source, dict) else None
    return value if isinstance(value, str) and len(value) <= 512 else None


def _unknown_part(socket, reason, hull=None):
    return {"socket_key": socket.get("key"), "component": socket.get("component"),
            "region": region_for_socket(hull, socket["key"]) if hull and socket.get("key") in hull["sockets"] else "unknown",
            "status": "unknown", "worst_packet": None, "threshold": None, "margin": None,
            "tested_paths": 0, "unknown_paths": 5, "supporting_sockets": [],
            "support_status": "unknown", "reason": reason, "paths": []}


def _unknown_ship(ship, reason):
    return {"ship_key": ship["key"], "ship_name": ship["name"], "status": "unknown", "summary": reason,
            "parts": [_unknown_part(s, reason) for s in ship.get("sockets", []) if s.get("component")],
            "suggestions": [], "tested_paths": 0, "unknown_paths": 5 * len(ship.get("components", []))}


def _dr(hull, occupied):
    fraction = len(occupied) / len(hull["sockets"])
    interpolation = min(1, max(0, (fraction - 0.2) / 0.4))
    return min(0.9, max(0, hull["min_component_dr"] +
                       (hull["max_component_dr"] - hull["min_component_dr"]) * interpolation))


def _stock_ship_problem(ship, hull, geometry):
    if hull.get("unsupported"):
        return "Hull geometry is incomplete: " + "; ".join(hull["unsupported"])
    if hull.get("stat_modifiers"):
        return "Relevant hull DT/DR modifiers are unsupported."
    if not isinstance(ship.get("sockets"), list):
        return "Saved socket identities are unavailable; no geometric placement is established."
    sockets = ship["sockets"]
    keys = [s.get("key") for s in sockets]
    if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
        return "Saved socket identities are missing or ambiguous."
    for socket in sockets:
        key, component = socket["key"], socket.get("component")
        if key not in hull["sockets"]:
            return "A saved socket is absent from this hull's geometry; load validity is unverified."
        if component:
            meta = geometry["components"].get(component)
            if meta is None or not fits_component(hull["sockets"][key], meta):
                return "A fitted component has unknown geometry or fails the socket fit rules."
            if meta.get("stat_modifiers"):
                return "A fitted component has unsupported DT/DR modifiers."
            if meta.get("unsupported"):
                return "A fitted component has unsupported collision or fit metadata."
            faction = meta.get("faction")
            if faction and faction != hull.get("faction"):
                return "Faction-shared equipment legality is not established for this hull."
    return None


def _colliders(hull, occupied):
    # Keep structure for raw query-capacity accounting, then filter it before
    # damage distribution as ShipController does (5553-5580).
    boxes = {key: hull["sockets"][key] for key in occupied}
    extras = {}
    for row in hull.get("other_colliders", []):
        key = "@hull:" + row["collider_id"]
        boxes[key] = row
        extras[key] = row
    return boxes, extras


def _probe(hull, boxes, extras, point, key, profile, direction):
    mode = profile.get("geometry_mode")
    if mode == "explosion":
        hits = sphere_hits(point, profile["geometry_radius"], boxes, list(boxes))
        # sphere_hits returns identities; overlap iteration order does not
        # matter for the supported evenly shared explosion profiles.
        keys = [hit["socket_key"] if isinstance(hit, dict) else hit for hit in hits]
        path = {"origin": list(point), "radius": profile["geometry_radius"]}
    else:
        path = path_from_point(hull, point, direction)
        length = min(path["length"], profile["geometry_distance"])
        hits = ray_hits(path["origin"], path["direction"], boxes, list(boxes), length)
        path["length"] = length
        keys = [hit["socket_key"] for hit in hits]
        # Unity skips origin-inside colliders. Being inside an approximate box
        # does not establish being inside its true capsule, so do not omit it.
        approximate = [k for k in extras if not extras[k]["exact"]]
        if sphere_hits(path["origin"], 1e-9, boxes, approximate):
            return keys, path, "Ray starts within approximate collider bounds; actual hits are unknown."
    if len(keys) >= QUERY_CAPACITY:
        return keys, path, "Query reaches the game's 20-collider buffer capacity; retained recipients are unknown."
    keys = [k for k in keys if k not in extras or extras[k]["kind"] != "structure"]
    if mode != "explosion":
        hits = [hit for hit in hits if hit["socket_key"] in keys]
        if profile["distribution"] == "first" and any(
            math.isclose(a["enter"], b["enter"], abs_tol=1e-6)
            for a, b in zip(hits, hits[1:], strict=False)
        ):
            return keys, path, "Overlapping entry distances leave AP recipient order ambiguous."
    if key not in keys:
        return keys, path, "The selected probe does not reach this target; protection is unknown."
    if any(k in extras and (not extras[k]["exact"] or extras[k]["kind"] == "unknown") for k in keys):
        return keys, path, "Probe intersects an unsupported or approximate hull-part collider."
    return keys, path, None


def _analyze(ship, hull, geometry, components, profile, direction, budget, target_keys=None):
    occupied = {s["key"]: s["component"] for s in ship["sockets"] if s.get("component")}
    boxes, extras = _colliders(hull, occupied)
    reduction = _dr(hull, occupied)
    output = []
    for key, component in occupied.items():
        if target_keys is not None and key not in target_keys:
            continue
        part = components.get(component)
        if not part:
            output.append(_unknown_part({"key": key, "component": component}, "No audited component DT in this model.", hull))
            continue
        row = _unknown_part({"key": key, "component": component}, "No complete probes.", hull)
        row["threshold"] = part["threshold"]
        row["center"] = list(hull["sockets"][key]["center"])
        packets, support_keys, support_unknown, support_vulnerable = [], set(), False, False
        for index, point in enumerate(target_points(hull["sockets"][key], direction)):
            if budget[0] <= 0:
                row["reason"] = "Analysis probe budget exhausted; remaining paths are unknown."
                break
            budget[0] -= 1
            keys, path, problem = _probe(hull, boxes, extras, point, key, profile, direction)
            sample = {"index": index, "geometry": path, "recipients": keys, "status": "unknown", "reason": problem}
            row["paths"].append(sample)
            if problem:
                row["reason"] = problem
                continue
            values = distribute_packets(profile, len(keys), reduction)
            packet = values[keys.index(key)]
            packets.append(packet)
            sample.update({"status": "threshold-exceeded" if packet > part["threshold"] else "within-dt",
                           "packet": packet, "margin": part["threshold"] - packet})
            for support, value in zip(keys, values, strict=True):
                if support == key:
                    continue
                support_keys.add(support)
                support_dt = extras[support].get("base_dt") if support in extras else components.get(occupied[support], {}).get("threshold")
                support_unknown |= support_dt is None
                support_vulnerable |= support_dt is not None and value > support_dt
        row["tested_paths"] = len(packets)
        row["unknown_paths"] = 5 - len(packets)
        row["supporting_sockets"] = sorted(support_keys)
        row["support_status"] = "vulnerable" if support_vulnerable else "unknown" if support_unknown or len(packets) < 5 else "within-dt"
        if packets:
            row["worst_packet"] = max(packets)
            row["margin"] = part["threshold"] - max(packets)
            if row["margin"] < 0:
                row["status"] = "threshold-exceeded"
                row["reason"] = "At least one sampled packet exceeds this target's DT; destruction still requires the health gate."
            elif row["unknown_paths"] == 0:
                row["status"] = "within-dt"
                row["reason"] = "Within DT on all five sampled paths only; HP loss and disablement remain possible."
        output.append(row)
    return output, reduction


def _suggest(ship, hull, geometry, components, profile, direction, baseline, budget):
    # Deliberately narrow: additive empty-magazine proposals preserve existing
    # fitted functions and ammunition. No unsupported replacement/load rewrite.
    filler = "Stock/Reinforced Magazine"
    meta = geometry["components"].get(filler)
    targets = {row["socket_key"] for row in baseline if row["status"] == "threshold-exceeded" and row["unknown_paths"] == 0}
    if not targets or not meta or filler not in components or meta.get("unsupported") or meta.get("stat_modifiers"):
        return []
    if meta.get("faction") and meta["faction"] != hull.get("faction"):
        return []
    occupied = {s["key"] for s in ship["sockets"] if s.get("component")}
    candidates = [key for key, socket in hull["sockets"].items() if key not in occupied and fits_component(socket, meta)]
    def distance(key):
        return min(sum((a - b) ** 2 for a, b in zip(hull["sockets"][key]["center"], hull["sockets"][target]["center"], strict=True)) for target in targets)
    candidates.sort(key=lambda key: (distance(key), key))
    original = {row["socket_key"]: row for row in baseline}
    suggestions = []
    for key in candidates[:MAX_CANDIDATES]:
        if budget[0] < 5 * (len(targets) + 1):
            break
        candidate = copy.deepcopy(ship)
        candidate["sockets"] = [s for s in candidate["sockets"] if s["key"] != key]
        candidate["sockets"].append({"key": key, "component": filler})
        candidate.setdefault("components", []).append(filler)
        after, reduction = _analyze(candidate, hull, geometry, components, profile, direction, budget, targets | {key})
        by_key = {row["socket_key"]: row for row in after}
        filler_result = by_key[key]
        # Do not recommend a recipient whose DT/coverage fails its own probes.
        if filler_result["status"] != "within-dt" or filler_result["unknown_paths"] or filler_result["support_status"] != "within-dt":
            continue
        improved = sorted(target for target in targets if by_key[target]["unknown_paths"] == 0 and
                          by_key[target]["support_status"] == "within-dt" and
                          by_key[target]["margin"] > original[target]["margin"])
        if not improved:
            continue
        before = min(original[target]["margin"] for target in improved)
        after_margin = min(by_key[target]["margin"] for target in improved)
        suggestions.append({
            "socket_key": key, "component": filler, "previous_component": None, "target_sockets": improved,
            "before_margin": before, "after_margin": after_margin, "damage_reduction_after": reduction,
            "changes": [{"socket_key": key, "from": None, "to": filler}],
            "status": "candidate", "validation": "socket-fit-and-sampled-packets-only",
            "summary": f"Test an empty Reinforced Magazine in {key}: improves the worst tested DT margin for {', '.join(improved)} from {before:g} to {after_margin:g} HP.",
            "limitations": ["Candidate, not an applied or fully validated build. Final points, mass, resources and ammunition capacity are not recalculated.",
                            "Single-component addition only; this is a bounded search, not an optimal-stack claim.",
                            "Protection depends on the sampled hit collections and continued participation of supporting parts."],
        })
    suggestions.sort(key=lambda row: (-row["after_margin"], row["socket_key"]))
    return suggestions[:3]


def review_protection(fleet, bundle, geometry=None, threat_id="hei", direction="bow"):
    """Return localized findings, candidate additions and overlay-ready part rows."""
    if not isinstance(fleet, dict) or not isinstance(fleet.get("ships"), list) or not 1 <= len(fleet["ships"]) <= MAX_SHIPS:
        raise FleetInputError("Protection review needs a bounded fleet snapshot.")
    socket_count = 0
    ship_keys = set()
    for ship in fleet["ships"]:
        if not isinstance(ship, dict) or any(not isinstance(ship.get(k), str) or not ship[k] or len(ship[k]) > MAX_ID_LENGTH
                                             for k in ("key", "name", "hull")):
            raise FleetInputError("Protection review needs ship identities.")
        if ship["key"] in ship_keys:
            raise FleetInputError("Protection review needs unique ship identities.")
        ship_keys.add(ship["key"])
        sockets = ship.get("sockets", [])
        if not isinstance(sockets, list) or any(not isinstance(s, dict) or any(
            s.get(k) is not None and (not isinstance(s[k], str) or len(s[k]) > MAX_ID_LENGTH)
            for k in ("key", "component")) for s in sockets):
            raise FleetInputError("Protection review needs bounded socket identities.")
        socket_count += len(sockets)
        if socket_count > MAX_SOCKETS or not isinstance(ship.get("components", []), list):
            raise FleetInputError("Protection review exceeds snapshot limits.")
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        raise FleetInputError("Choose protection direction: " + ", ".join(DIRECTIONS) + ".")
    if not isinstance(threat_id, str) or not threat_id or len(threat_id) > 100:
        raise FleetInputError("Choose a protection threat ID.")
    report = {"schema_version": 1, "engine_version": ENGINE_VERSION, "status": "unknown", "build_id": build_fingerprint(fleet),
              "bundle_id": _source_id(bundle, "bundle_id"), "geometry_id": _source_id(geometry, "geometry_id"),
              "threat_id": threat_id, "direction": direction, "evidence_scope": "geometry-sampled; entry/effect origin assumed",
              "limitations": list(_LIMITATIONS), "ships": [], "summary": "No geometry assessment available."}
    report["assessment_id"] = _id({k: report[k] for k in ("engine_version", "build_id", "bundle_id", "geometry_id", "threat_id", "direction")})
    problem = _model_problem(bundle)
    if not problem and not report["bundle_id"]:
        problem = "Damage knowledge bundle has no usable content identity."
    if not problem:
        problem = "Local geometry dataset is not installed; no automatic regional assessment was made." if geometry is None else geometry_problem(geometry)
    if not problem and geometry["game_version"] != bundle["damage_model"]["game_version"]:
        problem = "Geometry and damage-model game versions do not match."
    profile = next((p for p in bundle["damage_model"]["threats"] if p["id"] == threat_id), None) if not problem else None
    if not problem and (not profile or profile.get("geometry_mode") not in ("ray", "explosion") or
                        profile["distribution"] not in ("even", "first") or
                        (profile["geometry_mode"] == "explosion" and profile["distribution"] != "even")):
        problem = "This profile has no supported automatic path sampler; use the explicit packet calculator."
    if not problem:
        field = "geometry_distance" if profile["geometry_mode"] == "ray" else "geometry_radius"
        value = profile.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 100:
            problem = "Damage profile geometry parameters are invalid."
    if problem:
        report["limitations"].append(problem)
        report["summary"] = problem
        report["ships"] = [_unknown_ship(ship, problem) for ship in fleet["ships"]]
        return report
    components = {row["id"]: row for row in bundle["damage_model"]["components"]}
    report["game_version"] = geometry["game_version"]
    report["assumptions"] = [profile["assumption"]]
    report["evidence"] = list(bundle["damage_model"]["evidence"]) + [profile["source"] + " [SHA-256 " + profile["source_sha256"] + "]"]
    budget = [MAX_PROBES]
    for ship in fleet["ships"]:
        hull = geometry["hulls"].get(ship["hull"])
        reason = "Hull geometry is unavailable (including unsupported modular layouts)." if hull is None else _stock_ship_problem(ship, hull, geometry)
        if not reason and profile["geometry_mode"] == "explosion" and hull.get("sphere_query_complete") is not True:
            reason = "HE overlap completeness is unknown: the game's limited all-layer collider buffer is not reproduced. Use an explicit assumed hit collection."
        if reason:
            report["ships"].append(_unknown_ship(ship, reason))
            continue
        parts, reduction = _analyze(ship, hull, geometry, components, profile, direction, budget)
        exceeded = sum(row["status"] == "threshold-exceeded" for row in parts)
        assessed = sum(row["tested_paths"] > 0 for row in parts)
        unknown = sum(row["unknown_paths"] > 0 for row in parts)
        result = {"ship_key": ship["key"], "ship_name": ship["name"], "status": "assessed" if assessed else "unknown",
                  "summary": f"{exceeded} parts exceed DT on a tested path; {unknown} parts have incomplete or unknown coverage.",
                  "damage_reduction": reduction, "dr_provenance": "stock hull stats and fitted socket count",
                  "parts": parts, "tested_paths": sum(p["tested_paths"] for p in parts),
                  "unknown_paths": sum(p["unknown_paths"] for p in parts), "suggestions": []}
        result["suggestions"] = _suggest(ship, hull, geometry, components, profile, direction, parts, budget)
        report["ships"].append(result)
    assessed = sum(s["status"] == "assessed" for s in report["ships"])
    report["status"] = "assessed" if assessed else "unknown"
    report["summary"] = f"{assessed}/{len(report['ships'])} ships have sampled results for {threat_id} from {direction}; unassessed parts remain unknown."
    report["probes_used"] = MAX_PROBES - budget[0]
    report["provenance"] = list(geometry["provenance"])
    return report


def overlay_projection(assessment, *, build_id, geometry_id, bundle_id, threat_id, direction):
    """Project assessment rows, withholding stale colors after any input change."""
    requested = {"build_id": build_id, "geometry_id": geometry_id, "bundle_id": bundle_id,
                 "threat_id": threat_id, "direction": direction}
    current = assessment.get("engine_version") == ENGINE_VERSION and all(assessment.get(key) == value for key, value in requested.items())
    rows = []
    for ship in assessment.get("ships", []):
        for part in ship["parts"]:
            status = part["status"] if current else "unknown"
            support = part["support_status"] if current else "unknown"
            color = {"within-dt": "blue", "threshold-exceeded": "amber"}.get(status, "grey")
            if status == "within-dt" and support != "within-dt":
                color = "amber" if support == "vulnerable" else "grey"
            rows.append({"ship_key": ship["ship_key"], "socket_key": part["socket_key"],
                         "region": part["region"], "status": status,
                         "color": color,
                         "margin": part["margin"] if current else None,
                         "reason": part["reason"] if current else "Build or analysis selection changed; recompute before showing protection.",
                         "supporting_sockets": part["supporting_sockets"] if current else [],
                         "support_status": support,
                         "tested_paths": part["tested_paths"] if current else 0,
                         "unknown_paths": part["unknown_paths"] if current else 5,
                         "evidence_scope": assessment["evidence_scope"]})
    return {"schema_version": 1, "current": current, "assessment_id": assessment["assessment_id"], "parts": rows,
            "legend": {"blue": "Target and known supporting recipients within DT on five assumed samples only; not immunity.",
                       "amber": "A sampled target or supporting recipient exceeds DT; health gate still applies.",
                       "grey": "Incomplete, unsupported or stale evidence; no protection conclusion."}}

"""Conservative, explainable evaluation of observed fleet fitting."""

import copy
from collections import Counter

from .bundle import BundleError, check_predicates, reference_members, validate_check
from .damage import damage_inventory
from .protection import review_protection
from .parser import FleetInputError, MAX_AMMUNITION_LOADS, MAX_SHIPS, MAX_SOCKETS, MAX_NAME_LENGTH, MAX_ID_LENGTH

_LIMITATIONS = [
    "This is a partial review of saved fittings under curated advice, not a quality score or certification of a good ship.",
    "Points are the saved fleet total; costs, resource use, and compatibility have not been recalculated against the game.",
    "Power, crew, weapon arcs, armor, maneuvering, ammunition sufficiency, and point-defense coverage are not evaluated.",
    "A snapshot alone cannot establish physical damage paths. Optional local geometry adds a separate conditional sample report; explicit stack calculations use caller-assumed hit collections and DR.",
    "A fitted support provider does not establish communication range, formation, current availability, or survivability of that support.",
    "A selected role is a fleet discussion lens; individual ship roles are not inferred from names or assumed from that selection.",
]


def _validate_inputs(fleet, bundle):
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        raise BundleError("Unsupported bundle schema_version; expected 1.")
    if not isinstance(bundle.get("catalog"), dict):
        raise BundleError("Bundle catalog must be an object.")
    for field in ("components", "munitions", "hulls", "classes", "aliases"):
        if not isinstance(bundle["catalog"].get(field, {}), dict):
            raise BundleError(f"Bundle catalog {field} must be an object.")
    if not isinstance(bundle.get("checks"), list) or not isinstance(bundle.get("entries"), dict):
        raise BundleError("Bundle checks and entries must be an array and object respectively.")
    strategy = bundle.get("strategy")
    if not isinstance(strategy, dict):
        raise BundleError("Bundle strategy must be an object.")
    for field in ("principles", "roles", "examples"):
        if not isinstance(strategy.get(field, []), list) or any(not isinstance(v, dict) for v in strategy.get(field, [])):
            raise BundleError(f"Bundle strategy {field} must be an array of objects.")
    if not isinstance(bundle.get("diagnostics", []), list):
        raise BundleError("Bundle diagnostics must be an array.")
    if not isinstance(fleet, dict) or not isinstance(fleet.get("ships"), list):
        raise FleetInputError("Fleet snapshot must contain a ships array.")
    if not fleet["ships"] or len(fleet["ships"]) > MAX_SHIPS:
        raise FleetInputError(f"Fleet snapshot must contain 1 to {MAX_SHIPS} ships.")
    if not isinstance(fleet.get("name", ""), str) or len(fleet.get("name", "")) > MAX_NAME_LENGTH:
        raise FleetInputError("Design name exceeds the character limit.")
    custom_ids = fleet.get("custom_template_ids", [])
    if not isinstance(custom_ids, list) or any(not isinstance(v, str) or not v.startswith("$MODMIS$/") for v in custom_ids):
        raise FleetInputError("Custom template IDs must be local $MODMIS$/ identities.")
    socket_count = ammo_count = 0
    for ship in fleet["ships"]:
        if not isinstance(ship, dict) or any(not isinstance(ship.get(key), str) for key in ("key", "name", "hull")):
            raise FleetInputError("Each ship snapshot must have a string key, name, and hull.")
        if len(ship["name"]) > MAX_NAME_LENGTH or any(len(ship[key]) > MAX_ID_LENGTH for key in ("key", "hull")):
            raise FleetInputError("Ship name or identity exceeds the character limit.")
        if not isinstance(ship.get("components"), list) or any(not isinstance(c, str) for c in ship["components"]):
            raise FleetInputError("Ship components must be an array of component IDs.")
        if any(len(c) > MAX_ID_LENGTH for c in ship["components"]):
            raise FleetInputError("Component identity exceeds the character limit.")
        if not isinstance(ship.get("ammunition"), dict) or any(
            not isinstance(k, str) or len(k) > MAX_ID_LENGTH or type(v) is not int or v < 0
            for k, v in ship["ammunition"].items()
        ):
            raise FleetInputError("Ship ammunition must map IDs to nonnegative integer quantities.")
        socket_count += len(ship["components"])
        ammo_count += len(ship["ammunition"])
    if socket_count > MAX_SOCKETS or ammo_count > MAX_AMMUNITION_LOADS:
        raise FleetInputError("Fleet snapshot exceeds socket or ammunition limits.")


def _amount(reference, ship, catalog, *, ammunition_only=False):
    members = reference_members(reference, catalog)
    counts = Counter(ship["components"])
    return sum(
        (ship["ammunition"].get(member, 0) if member in catalog.get("munitions", {}) else
         (0 if ammunition_only else counts[member]))
        for member in members
    )


def _display(reference, catalog):
    if reference.startswith("class:"):
        return reference[6:].replace("-", " ")
    return catalog.get("components", {}).get(reference, catalog.get("munitions", {}).get(reference, reference))


def _matches(check, ship, catalog):
    evidence = []
    for kind, value in check_predicates(check):
        if kind == "count_lt":
            actual = _amount(value["component"], ship, catalog)
            if actual >= value["n"]:
                return None
            evidence.append(f"{_display(value['component'], catalog)}: {actual} fitted; advice threshold {value['n']}.")
        else:
            for reference in value if isinstance(value, list) else [value]:
                actual = _amount(reference, ship, catalog, ammunition_only=kind == "ammo_missing")
                if (kind == "has" and actual == 0) or (kind != "has" and actual > 0):
                    return None
                suffix = "loaded" if kind == "ammo_missing" else "present in the saved fitting"
                evidence.append(f"{_display(reference, catalog)}: {actual} {suffix}.")
    return evidence


def review_fleet(fleet: dict, bundle: dict, role: str | None = None, excluded_entry_ids=(),
                 investment="standard", *, geometry=None, protection_threat="hei", protection_direction="bow") -> dict:
    """Return cited findings and manual strategy without mutating either input.

    Unknown equipment disables checks on its ship: absence cannot establish a
    missing capability when the catalog cannot interpret the entire fitting.
    """
    _validate_inputs(fleet, bundle)
    if investment not in {"standard", "lean"}:
        raise FleetInputError("Choose investment standard or lean.")
    catalog, strategy = bundle["catalog"], bundle["strategy"]
    if role is not None and (not isinstance(role, str) or not any(r.get("id") == role for r in strategy.get("roles", []))):
        raise FleetInputError("Unknown review role; choose a role ID from the strategy bundle.")
    if isinstance(excluded_entry_ids, (str, bytes)):
        raise FleetInputError("Excluded entry IDs must be a collection, not a single string.")
    try:
        excluded = set(excluded_entry_ids)
    except TypeError as exc:
        raise FleetInputError("Excluded entry IDs must be an iterable of strings.") from exc
    if any(not isinstance(value, str) for value in excluded):
        raise FleetInputError("Excluded entry IDs must be strings.")
    limitations = list(_LIMITATIONS)
    if investment == "lean":
        limitations.append("Lean/cringed investment is intentional reduced protection or recovery. Essential weapon dependencies still apply; identify which fleet members use this posture.")
    limitations.extend(str(item) for item in bundle.get("diagnostics", []))
    if excluded:
        limitations.append("Checks linked to removed advice entries have been excluded from this review.")
    if not bundle.get("catalog_version"):
        limitations.append("The catalog has no consistent game version; automated ship checks were skipped.")
    missing_catalog = [key for key in ("components", "munitions", "hulls") if not catalog.get(key)]
    if missing_catalog:
        limitations.append("Incomplete catalog (" + ", ".join(missing_catalog) + "); automated ship checks were skipped.")
    custom_ids = set(fleet.get("custom_template_ids", []))
    known_components, known_ammo = set(catalog.get("components", {})), set(catalog.get("munitions", {}))
    unknown_ids, interpretable = set(), {}
    for index, ship in enumerate(fleet["ships"]):
        unknown = set(ship["components"]) - known_components
        unknown.update(key for key, count in ship["ammunition"].items() if count > 0 and key not in known_ammo | custom_ids)
        if ship["hull"] not in catalog.get("hulls", {}):
            unknown.add(ship["hull"])
        unknown_ids.update(unknown)
        interpretable[index] = not unknown
        if unknown:
            limitations.append(f"{ship['name']}: ship checks skipped because hull or equipment IDs are unknown: {', '.join(sorted(unknown))}.")
    findings, seen_checks = [], set()
    for check in bundle["checks"]:
        problem = validate_check(check, catalog, bundle["entries"])
        check_id = check.get("id", "<unnamed>") if isinstance(check, dict) else "<unnamed>"
        if not problem and check_id in seen_checks:
            problem = "duplicate check ID"
        if problem:
            limitations.append(f"Skipped check {check_id}: {problem}.")
            continue
        seen_checks.add(check_id)
        if check["advice_id"] in excluded or missing_catalog or not bundle.get("catalog_version"):
            continue
        entry = bundle["entries"][check["advice_id"]]
        for index, ship in enumerate(fleet["ships"]):
            if not interpretable[index]:
                continue
            hull_info = catalog["hulls"][ship["hull"]]
            if not isinstance(hull_info, dict):
                limitations.append(f"{ship['name']}: invalid hull metadata; ship checks skipped.")
                continue
            if check.get("hulls") and ship["hull"] not in check["hulls"]:
                continue
            if check.get("factions") and hull_info.get("faction") not in check["factions"]:
                continue
            evidence = _matches(check, ship, catalog)
            if evidence is None:
                continue
            providers = []
            shared = check.get("shared_capability")
            # Shared advice only applies if the capability is actually absent
            # locally. Existence elsewhere demonstrates a dependency, not safety.
            if shared and _amount(shared, ship, catalog) == 0:
                providers = [
                    other["name"] for other_index, other in enumerate(fleet["ships"])
                    if other_index != index and interpretable[other_index] and _amount(shared, other, catalog) > 0
                ]
            message = check["message"]
            if providers:
                message += " Potential fleet providers are listed separately. Range, communication, formation, and availability have not been established."
            findings.append({
                "check_id": check_id,
                "advice_id": check["advice_id"],
                "ship_key": ship["key"],
                "ship_name": ship["name"],
                "dimension": check["dimension"],
                "severity": "info" if providers else check["severity"],
                "title": check["title"],
                "message": message,
                "evidence": evidence,
                "source_url": entry.get("source_url", ""),
                "reason": entry.get("reason", ""),
                "author": entry.get("author", ""),
                "curated": entry.get("curated"),
                "verified_version": entry.get("verified_version"),
                "confidence": entry.get("status", "community-guidance"),
                "providers": providers,
            })
    if not bundle["checks"]:
        limitations.append("No executable checks were available; use the manual strategy guide.")
    output_strategy = copy.deepcopy(strategy)
    output_strategy["role"] = next((copy.deepcopy(item) for item in strategy.get("roles", []) if item.get("id") == role), None)
    return {
        "schema_version": 1,
        "bundle_id": bundle.get("bundle_id"),
        "catalog_version": bundle.get("catalog_version"),
        "fleet_name": fleet.get("name", "Unnamed fleet"),
        "kind": fleet.get("kind", "fleet"),
        "declared_points": fleet.get("declared_points"),
        "role": role,
        "investment": investment,
        "damage_inventory": damage_inventory(fleet, bundle),
        "protection": review_protection(fleet, bundle, geometry, protection_threat, protection_direction),
        "findings": findings,
        "unknown_ids": sorted(unknown_ids),
        "limitations": list(dict.fromkeys(limitations)),
        "strategy": output_strategy,
    }

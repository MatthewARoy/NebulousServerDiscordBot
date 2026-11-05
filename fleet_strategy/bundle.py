"""Load portable, versioned strategy data without importing the bot's knowledge code."""

import datetime
import hashlib
import json
from pathlib import Path
import tomllib

from .damage import validate_damage_model


class BundleError(ValueError):
    """Strategy data cannot be loaded or has an unsupported top-level schema."""


def _json_value(value):
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _read(path, diagnostics, *, required=False):
    try:
        return _json_value(tomllib.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        message = f"Could not load {path.name}: {exc}"
        if required:
            raise BundleError(message) from exc
        diagnostics.append(message)
        return {}


def _records(data, key, diagnostics):
    records = data.get(key, [])
    if not isinstance(records, list):
        diagnostics.append(f"Invalid {key} records: expected an array.")
        return []
    valid = []
    for record in records:
        if isinstance(record, dict):
            valid.append(record)
        else:
            diagnostics.append(f"Skipped malformed {key} record.")
    return valid


def reference_members(reference, catalog):
    """Resolve exact component/munition IDs or a nonempty, fully resolved class."""
    if not isinstance(reference, str) or not reference:
        return None
    known = set(catalog.get("components", {})) | set(catalog.get("munitions", {}))
    if reference.startswith("class:"):
        members = catalog.get("classes", {}).get(reference[6:])
        if not isinstance(members, list) or not members or any(not isinstance(m, str) or m not in known for m in members):
            return None
        return members
    return [reference] if reference in known else None


def check_predicates(check):
    """Normalize a predicate table or an array of tables to ordered AND terms."""
    value = check.get("when")
    tables = value if isinstance(value, list) else [value]
    if not tables or any(not isinstance(table, dict) or not table for table in tables):
        return None
    return [(kind, value) for table in tables for kind, value in table.items()]


def validate_check(check, catalog, entries):
    """Return a diagnostic, never execute data as code or guess an unknown predicate."""
    if not isinstance(check, dict):
        return "check must be an object"
    for field in ("id", "advice_id", "dimension", "title", "message", "severity"):
        if not isinstance(check.get(field), str) or not check[field].strip():
            return f"missing or invalid {field}"
    if check["severity"] not in {"info", "warn"}:
        return "unsupported severity"
    if check["advice_id"] not in entries or not isinstance(entries[check["advice_id"]], dict):
        return "unresolved advice_id"
    predicates = check_predicates(check)
    if predicates is None:
        return "when must contain explicit predicates"
    for kind, value in predicates:
        if kind in {"has", "missing", "ammo_missing"}:
            refs = value if isinstance(value, list) else [value]
            if not refs or any(reference_members(ref, catalog) is None for ref in refs):
                return f"unresolved or invalid {kind} reference"
            if kind == "ammo_missing" and any(
                member not in catalog.get("munitions", {}) for ref in refs for member in reference_members(ref, catalog)
            ):
                return "ammo_missing must reference munitions"
        elif kind == "count_lt":
            if not isinstance(value, dict) or set(value) != {"component", "n"}:
                return "count_lt requires only component and n"
            if reference_members(value["component"], catalog) is None:
                return "unresolved count_lt reference"
            if type(value["n"]) is not int or value["n"] < 1:
                return "count_lt n must be a positive integer"
        else:
            return f"unsupported predicate {kind}"
    for field in ("factions", "hulls"):
        values = check.get(field)
        if values is not None and (not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values)):
            return f"invalid {field} filter"
    if "hulls" in check and any(hull not in catalog.get("hulls", {}) for hull in check["hulls"]):
        return "unresolved hull filter"
    if "roles" in check:
        return "per-ship role predicates require a separately established ship role"
    if "factions" in check and any(faction not in {"ans", "osp", "civilian"} for faction in check["factions"]):
        return "unsupported faction filter"
    if "shared_capability" in check and reference_members(check["shared_capability"], catalog) is None:
        return "unresolved shared_capability"
    return None


def load_bundle(knowledge_dir: Path) -> dict:
    """Load knowledge files into one deterministic, JSON-serializable bundle.

    Unusable checks are omitted and explained in diagnostics. Missing catalogs
    remain visible and cannot create reassuring negative-evidence findings.
    """
    root = Path(knowledge_dir)
    diagnostics = []
    strategy = _read(root / "strategy" / "strategy.toml", diagnostics, required=True)
    checks_data = _read(root / "strategy" / "checks.toml", diagnostics, required=True)
    damage_model = _read(root / "strategy" / "damage.toml", diagnostics)
    damage_problem = validate_damage_model(damage_model)
    if damage_problem:
        diagnostics.append(damage_problem)
        damage_model = {}  # Keep malformed optional data (including NaN) out of the bundle hash.
    if strategy.get("schema_version") != 1 or checks_data.get("schema_version") != 1:
        raise BundleError("Unsupported strategy/check schema_version; expected 1.")
    for field in ("principles", "roles", "examples"):
        records = strategy.get(field)
        if not isinstance(records, list) or any(
            not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in ("id", "title", "summary"))
            for item in records
        ):
            raise BundleError(f"Strategy {field} must contain objects with id, title, and summary.")
        if len({item["id"] for item in records}) != len(records):
            raise BundleError(f"Strategy {field} contains duplicate IDs.")
    components = _read(root / "catalog" / "components.toml", diagnostics)
    hulls = _read(root / "catalog" / "hulls.toml", diagnostics)
    classes = _read(root / "catalog" / "classes.toml", diagnostics)
    aliases = _read(root / "catalog" / "aliases.toml", diagnostics)
    catalog = {"components": {}, "munitions": {}, "hulls": {}, "classes": {}, "aliases": {}}
    for field, singular in (("components", "component"), ("munitions", "munition")):
        for record in _records(components, singular, diagnostics):
            if isinstance(record.get("id"), str) and isinstance(record.get("display"), str):
                if record["id"] in catalog[field]:
                    diagnostics.append(f"Duplicate catalog ID: {record['id']}.")
                catalog[field][record["id"]] = record["display"]
            else:
                diagnostics.append(f"Skipped {singular} with invalid id/display.")
    for record in _records(hulls, "hull", diagnostics):
        if all(isinstance(record.get(field), str) for field in ("id", "display", "class", "faction")):
            catalog["hulls"][record["id"]] = {key: record[key] for key in ("display", "class", "faction")}
        else:
            diagnostics.append("Skipped hull with invalid id/display/class/faction.")
    for record in _records(classes, "class", diagnostics):
        if isinstance(record.get("name"), str) and isinstance(record.get("members"), list):
            catalog["classes"][record["name"]] = record["members"]
        else:
            diagnostics.append("Skipped malformed component class.")
    for record in _records(aliases, "alias", diagnostics):
        if isinstance(record.get("id"), str) and isinstance(record.get("names"), list):
            for alias in record["names"]:
                if isinstance(alias, str):
                    catalog["aliases"][alias] = record["id"]
    entries = {}
    for path in sorted((root / "entries").glob("*.toml")):
        for record in _records(_read(path, diagnostics), "entry", diagnostics):
            if not isinstance(record.get("id"), str):
                diagnostics.append(f"Skipped entry without an ID in {path.name}.")
            elif record["id"] in entries:
                raise BundleError(f"Duplicate advice ID: {record['id']}.")
            else:
                entries[record["id"]] = record
    versions = {d["catalog_version"] for d in (components, hulls) if isinstance(d.get("catalog_version"), str)}
    catalog_version = next(iter(versions)) if len(versions) == 1 else None
    if len(versions) != 1 or not all(d.get("catalog_version") for d in (components, hulls)):
        diagnostics.append("Catalog version is missing or inconsistent; catalog checks are incomplete.")
        catalog_version = None
    for field in ("components", "munitions", "hulls"):
        if not catalog[field]:
            diagnostics.append(f"Catalog {field} is empty; related checks cannot be completed.")
    checks, seen = [], set()
    for check in _records(checks_data, "checks", diagnostics):
        problem = validate_check(check, catalog, entries)
        if isinstance(check.get("id"), str) and check["id"] in seen:
            problem = "duplicate check ID"
        if problem:
            diagnostics.append(f"Skipped check {check.get('id', '<unnamed>')}: {problem}.")
        else:
            checks.append(check)
            seen.add(check["id"])
    bundle = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "damage_model": damage_model,
        "strategy": strategy,
        "checks": checks,
        "entries": entries,
        "catalog": catalog,
        "diagnostics": diagnostics,
    }
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    bundle["bundle_id"] = hashlib.sha256(encoded).hexdigest()
    return bundle

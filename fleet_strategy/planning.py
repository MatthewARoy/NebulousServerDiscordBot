"""Turn an explicit design brief into a portable, reviewable planning outline.

Planning selects questions and reference material. It never invents a legal fit,
recalculates costs from a save, or ranks templates by their names.
"""

from copy import deepcopy

from .bundle import BundleError


def plan_design(bundle, *, faction, role, budget=3000, scope="fleet",
                investment="standard", targets=(), support=(), templates=()):
    """Create a JSON-compatible plan for a fleet or individual ship.

    ``templates`` contains normalized snapshots returned by ``parse_design``.
    They are optional reference candidates, never silently installed or changed.
    A fleet investment setting is a review lens; each member needs its own brief.
    """
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        raise BundleError("Unsupported strategy bundle schema.")
    if faction not in {"ans", "osp"}:
        raise ValueError("Choose faction ans or osp.")
    if scope not in {"fleet", "ship"}:
        raise ValueError("Choose scope fleet or ship.")
    if investment not in {"standard", "lean"}:
        raise ValueError("Choose investment standard or lean.")
    if type(budget) is not int or budget <= 0:
        raise ValueError("Budget must be a positive whole number of points.")
    strategy = bundle.get("strategy", {})
    roles = {item["id"]: item for item in strategy.get("roles", [])}
    if role not in roles:
        raise ValueError("Unknown role. Choose: " + ", ".join(roles))
    for values in (targets, support):
        if not isinstance(values, (list, tuple)) or not all(isinstance(item, str) for item in values):
            raise ValueError("Targets and support must be lists of text.")

    hulls = bundle.get("catalog", {}).get("hulls", {})
    candidates = []
    for template in templates:
        if template.get("kind") != "ship" or len(template.get("ships", [])) != 1:
            raise ValueError("Template candidates must be parsed individual .ship designs.")
        ship = template["ships"][0]
        hull = hulls.get(ship.get("hull"), {})
        if hull.get("faction") != faction:
            continue
        candidates.append({
            "name": ship.get("name", "Unnamed ship"),
            "hull": ship.get("hull"),
            "declared_points": template.get("declared_points"),
            "selection_status": "Faction-compatible reference; role, current cost, and fit need review.",
        })

    return deepcopy({
        "schema_version": 1,
        "bundle_id": bundle.get("bundle_id"),
        "catalog_version": bundle.get("catalog_version"),
        "status": "planning-guidance",
        "brief": {"scope": scope, "faction": faction, "role": role, "budget": budget,
                  "investment": investment, "targets": list(targets), "support": list(support)},
        "role": roles[role],
        "investment_mode": next((item for item in strategy.get("investment_modes", [])
                                 if item["id"] == investment), None),
        "principles": strategy.get("principles", []),
        "layout_concepts": strategy.get("layout_concepts", []),
        "steps": strategy.get("build_sequence", []),
        "reference_examples": [item for item in strategy.get("examples", [])
                               if item.get("faction") == faction
                               and (not item.get("roles") or role in item["roles"])],
        "template_candidates": candidates,
        "limitations": [
            "This is a design brief and review sequence, not a generated or game-validated ship fit.",
            "Template costs are saved values, not current game calculations; candidates are not ranked by quality.",
            "For a fleet, assign roles and deliberate lean-investment exceptions to individual ships.",
            "Confirm socket geometry, power, crew, capacity, cost, and missile/craft dependencies in the game before saving.",
        ] + list(bundle.get("diagnostics", [])),
    })

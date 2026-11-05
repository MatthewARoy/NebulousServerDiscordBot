"""Actual bundle, portable fixtures, planning, and no-bot CLI integration."""

import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from fleet_strategy import load_bundle, parse_design, review_fleet
from fleet_strategy.planning import plan_design

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "fleet_strategy/conformance.json").read_text(encoding="utf-8"))["cases"]


@pytest.fixture
def bundle():
    return load_bundle(ROOT / "knowledge")


def test_real_bundle_has_reviewable_sources_and_strategy(bundle):
    assert not bundle["diagnostics"]
    assert len(bundle["checks"]) == 5
    assert len(bundle["entries"]) == 47
    assert len(bundle["strategy"]["principles"]) == 6
    assert len(bundle["strategy"]["roles"]) == 7
    assert {item["id"] for item in bundle["strategy"]["investment_modes"]} == {"standard", "lean"}
    assert {item["id"] for item in bundle["strategy"]["layout_concepts"]} >= {"protected-regions", "reinforced-stacks"}
    for check in bundle["checks"]:
        entry = bundle["entries"][check["advice_id"]]
        assert entry["source_url"].startswith("https://discord.com/channels/")
        assert entry["reason"]
        assert "verified_version" not in entry  # Do not fabricate a fresh verification pass.


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_portable_conformance(case, bundle):
    original = copy.deepcopy(case["snapshot"])
    report = review_fleet(case["snapshot"], bundle,
                          investment=case.get("investment", "standard"),
                          excluded_entry_ids=case.get("excluded_entry_ids", ()))
    fields = ("check_id", "ship_key", "severity", "providers")
    findings = [{key: row[key] for key in fields} for row in report["findings"]]
    assert findings == case["expected_findings"]
    assert report["unknown_ids"] == case["expected_unknown_ids"]
    assert case["snapshot"] == original
    assert report["limitations"]
    roundtrip = json.loads(json.dumps(bundle))
    assert review_fleet(case["snapshot"], roundtrip,
                        investment=case.get("investment", "standard"),
                        excluded_entry_ids=case.get("excluded_entry_ids", ())) == report


def test_planning_is_explicit_and_does_not_price_or_rank_templates(bundle):
    template = parse_design(b"<Ship><Name>Reference</Name><Cost>400</Cost>"
                            b"<HullType>Stock/Keystone Destroyer</HullType><SocketMap/></Ship>")
    plan = plan_design(bundle, faction="ans", role="denial", budget=300,
                       scope="ship", investment="lean", templates=[template],
                       support=["Scout provides tracks"])
    assert plan["brief"]["budget"] == 300
    assert plan["brief"]["investment"] == "lean"
    assert plan["template_candidates"][0]["declared_points"] == 400
    assert "current cost" in plan["template_candidates"][0]["selection_status"]
    assert plan["status"] == "planning-guidance"
    assert plan["layout_concepts"] and len(plan["steps"]) == 6
    assert all(row["faction"] == "ans" and "denial" in row["roles"] for row in plan["reference_examples"])
    plan["role"]["title"] = "changed by caller"
    assert bundle["strategy"]["roles"][2]["title"] != "changed by caller"


@pytest.mark.parametrize("override", [{"budget": 0}, {"budget": True}, {"faction": "unknown"},
                                      {"role": "auto"}, {"investment": "invincible"}, {"scope": "wing"}])
def test_planning_rejects_ambiguous_briefs(bundle, override):
    arguments = {"faction": "ans", "role": "frontline"} | override
    with pytest.raises(ValueError):
        plan_design(bundle, **arguments)


def test_cli_exports_without_site_packages_and_roundtrips(tmp_path, bundle):
    target = tmp_path / "bundle.json"
    result = subprocess.run([sys.executable, "-S", "-m", "fleet_strategy", "export", "--out", str(target)],
                            cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    exported = json.loads(target.read_text(encoding="utf-8"))
    assert exported == bundle
    assert len(exported["bundle_id"]) == 64
    plan = subprocess.run([sys.executable, "-S", "-m", "fleet_strategy", "plan", "--faction", "osp",
                           "--role", "skirmish", "--budget", "3000"],
                          cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["brief"]["faction"] == "osp"

"""Local review, planning, and portable bundle export. No game or bot needed."""

import argparse
import json
from pathlib import Path
import sys

from . import BundleError, FleetInputError, MAX_FLEET_BYTES, load_bundle, parse_design, review_fleet
from .planning import plan_design
from .damage import evaluate_stack
from .geometry import load_geometry


def _read_design(path):
    with path.open("rb") as source:
        # Read one extra byte so an oversize file is rejected without loading it all.
        return parse_design(source.read(MAX_FLEET_BYTES + 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge", type=Path, default=Path("knowledge"),
                        help="Canonical knowledge directory (default: ./knowledge)")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="Review a .fleet or .ship without changing it")
    review.add_argument("design", type=Path)
    review.add_argument("--role")
    review.add_argument("--stack", help="Assumed hit collection: SHIP_KEY:SOCKET,SOCKET, in hit order")
    review.add_argument("--threat", help="Audited damage profile ID, e.g. hei or 450-ap")
    review.add_argument("--dr", type=float, help="Explicit assumed hull DR fraction (0 through 0.9)")
    review.add_argument("--geometry", type=Path, help="Local geometry JSON generated from your game installation")
    review.add_argument("--direction", help="Automatic probe direction (default: bow)")
    review.add_argument("--investment", choices=("standard", "lean"), default="standard")
    review.add_argument("--exclude-advice", action="append", default=[],
                        help="Suppress a removed advice ID; repeatable")
    plan = commands.add_parser("plan", help="Create an explicit fleet or ship design brief")
    plan.add_argument("--faction", choices=("ans", "osp"), required=True)
    plan.add_argument("--role", required=True)
    plan.add_argument("--budget", type=int, default=3000)
    plan.add_argument("--scope", choices=("fleet", "ship"), default="fleet")
    plan.add_argument("--investment", choices=("standard", "lean"), default="standard")
    plan.add_argument("--target", action="append", default=[])
    plan.add_argument("--support", action="append", default=[])
    plan.add_argument("--template", type=Path, action="append", default=[])
    export = commands.add_parser("export", help="Export one content-addressed strategy/catalog/advice bundle")
    export.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundle = load_bundle(args.knowledge)
        if args.command == "export":
            if bundle.get("diagnostics"):
                raise BundleError("Resolve bundle diagnostics before export: " + "; ".join(bundle["diagnostics"]))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Wrote {args.out} ({bundle['bundle_id']})")
            return 0
        if args.command == "review":
            snapshot = _read_design(args.design)
            result = review_fleet(snapshot, bundle, role=args.role,
                                  investment=args.investment, excluded_entry_ids=args.exclude_advice,
                                  geometry=load_geometry(args.geometry) if args.geometry else None,
                                  protection_threat=args.threat or "hei", protection_direction=args.direction or "bow")
            if any(value is not None for value in (args.stack, args.dr)):
                if any(value is None for value in (args.stack, args.threat, args.dr)) or ':' not in args.stack:
                    raise FleetInputError("Supply --stack SHIP_KEY:SOCKET,SOCKET, --threat ID and --dr FRACTION together.")
                if args.direction:
                    raise FleetInputError("--direction selects automatic probes; omit it for an explicit --stack scenario.")
                ship_key, sockets = args.stack.split(':', 1)
                result['damage_scenario'] = evaluate_stack(
                    snapshot, bundle, ship_key=ship_key, socket_keys=sockets.split(','),
                    threat_id=args.threat, damage_reduction=args.dr,
                )
        else:
            result = plan_design(bundle, faction=args.faction, role=args.role, budget=args.budget,
                                 scope=args.scope, investment=args.investment, targets=args.target,
                                 support=args.support, templates=[_read_design(path) for path in args.template])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (BundleError, FleetInputError, ValueError, OSError) as exc:
        print(f"fleet_strategy: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

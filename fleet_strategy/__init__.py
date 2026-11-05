"""Portable fleet strategy: standard-library-only, no Discord, Django, or game runtime.

The public inputs and outputs are JSON-compatible dictionaries; saved fleet points
and equipment are observations, not certification of a ship's combat performance.
"""

from .bundle import BundleError, load_bundle
from .damage import damage_inventory, destruction_gate, evaluate_stack
from .geometry import load_geometry
from .protection import overlay_projection, review_protection
from .parser import MAX_FLEET_BYTES, FleetInputError, parse_design, parse_fleet
from .planning import plan_design
from .review import review_fleet

__all__ = ["BundleError", "FleetInputError", "MAX_FLEET_BYTES", "load_bundle", "parse_design", "parse_fleet",
           "review_fleet", "plan_design", "damage_inventory", "destruction_gate", "evaluate_stack",
           "load_geometry", "review_protection", "overlay_projection"]

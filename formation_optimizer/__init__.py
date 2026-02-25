"""
Formation Optimizer - A standalone tool for optimizing Nebulous Fleet formations.

This module provides tools for compacting fleet formations while maintaining
minimum distances between ships, with visualization and animation capabilities.
"""

from .formation_optimizer import (
    compact_formation,
    optimize_fleet_file,
    visualize_formation_comparison,
    create_formation_animation,
    create_formation_animation_gif,
    FLEET_UNIT_TO_METERS,
)

__all__ = [
    'compact_formation',
    'optimize_fleet_file',
    'visualize_formation_comparison',
    'create_formation_animation',
    'create_formation_animation_gif',
    'FLEET_UNIT_TO_METERS',
]


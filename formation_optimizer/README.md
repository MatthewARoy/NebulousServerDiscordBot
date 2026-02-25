# Formation Optimizer

A standalone tool for optimizing Nebulous Fleet formations. This tool compacts fleet formations while maintaining minimum distances between ships, with visualization and animation capabilities.

## Features

- **Formation Optimization**: Compact fleet formations while maintaining minimum distances
- **3D Visualization**: Generate side-by-side comparisons of before/after formations
- **Animated GIFs**: Create animations showing the optimization process
- **Unit Conversion**: Handles conversion between user-facing meters and fleet file 10-meter increments
- **Formation Variants**: 
  - `-planar`: Creates a vertical plane formation facing forward (ships flatten forward/back but can spread left/right and up/down)
  - `-symmetrical`: Creates more symmetrical formations around axes

## Coordinate System

The formation optimizer uses the following coordinate system (relative to leader):
- **X-axis**: Right side = -x, Left side = +x
- **Y-axis**: Above = +y, Below = -y  
- **Z-axis**: Behind = +z, In front = -z

For planar formations, ships are flattened along the Z-axis (forward/back) while maintaining freedom to spread in X (left/right) and Y (up/down) directions.

## Installation

The formation optimizer requires the following dependencies (already in main `requirements.txt`):

- `numpy>=1.24.0`
- `matplotlib`
- `Pillow>=10.0.0` (for GIF generation)
- `imageio>=2.0.0` (fallback for GIF generation)

## Usage

### From Discord Bot

The formation optimizer is integrated into the Discord bot via the `!formation` command:

```
!formation [min_radius]
```

Where `min_radius` is the minimum distance in meters (default: 350 meters).

### Standalone Usage

```python
from formation_optimizer import optimize_fleet_file, create_formation_animation_gif

# Optimize a fleet file
result = optimize_fleet_file('path/to/fleet.fleet', min_distance_meters=350.0, capture_animation=True)
optimized_path, before_positions, after_positions, ship_names, intermediate_states = result

# Create animated GIF
gif_path = create_formation_animation_gif('path/to/fleet.fleet', min_distance_meters=350.0)
```

## Testing

Run tests from the project root:

```bash
# Run unit tests
python -m unittest formation_optimizer.tests.test_formation_optimizer

# Run visualization tests
python formation_optimizer/tests/test_formation_visualization.py
```

## Directory Structure

```
formation_optimizer/
├── __init__.py              # Package initialization and exports
├── formation_optimizer.py   # Main optimization and visualization code
├── README.md                 # This file
└── tests/
    ├── __init__.py
    ├── test_formation_optimizer.py      # Unit tests
    ├── test_formation_visualization.py   # Visualization tests
    ├── data/                             # Test fleet files
    │   └── d0f246ea-66a7-4c83-a11a-120feb24474d.fleet
    └── outputs/                          # Test output files (GIFs, PNGs)
```

## Integration with Discord Bot

The Discord bot imports the formation optimizer as a standalone module:

```python
from formation_optimizer import optimize_fleet_file, create_formation_animation
```

This keeps the formation optimizer code separate from the main bot codebase while still allowing integration.


#!/usr/bin/env python
"""
Standalone script to test formation visualization locally.
Generates and saves visualization images for manual inspection.

Usage:
    python test_formation_visualization.py [fleet_file] [min_radius]
    
Examples:
    python test_formation_visualization.py
    python test_formation_visualization.py d0f246ea-66a7-4c83-a11a-120feb24474d.fleet 35
"""
import sys
import os
from pathlib import Path

# Add project root to path (go up to tests, then to formation_optimizer, then to project root)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Test data directory
test_data_dir = Path(__file__).parent / "data"

from formation_optimizer.formation_optimizer import (
    optimize_fleet_file, 
    visualize_formation_comparison,
    create_formation_animation_gif
)


def test_visualization(fleet_file=None, min_radius_meters=350.0, open_image=False, create_gif=False):
    """
    Test formation visualization and save images.
    
    Args:
        fleet_file: Path to fleet file (defaults to test file in project root)
        min_radius_meters: Minimum radius for optimization in METERS (default: 350.0)
        open_image: Whether to open the image automatically (default: False)
        create_gif: Whether to generate animated GIF (default: False)
    """
    # Default to test fleet file if not provided
    if fleet_file is None:
        fleet_file = test_data_dir / "d0f246ea-66a7-4c83-a11a-120feb24474d.fleet"
    
    fleet_file = Path(fleet_file)
    
    if not fleet_file.exists():
        print(f"❌ Error: Fleet file not found: {fleet_file}")
        print(f"   Please provide a valid fleet file path.")
        return False
    
    print(f"📁 Loading fleet file: {fleet_file.name}")
    print(f"⚙️  Minimum radius: {min_radius_meters} meters")
    print()
    
    try:
        # Optimize the fleet file (min_radius_meters is in meters)
        print("🔄 Optimizing formation...")
        result = optimize_fleet_file(str(fleet_file), min_distance_meters=min_radius_meters)
        optimized_path, before_positions, after_positions, ship_names = result
        
        print(f"✅ Optimization complete!")
        print(f"   Optimized file: {optimized_path}")
        print()
        
        # Count ships
        ships_before = {k: v for k, v in before_positions.items() if k != "leader"}
        ships_after = {k: v for k, v in after_positions.items() if k != "leader"}
        print(f"📊 Formation stats:")
        print(f"   Ships in formation: {len(ships_before)}")
        print()
        
        # Generate visualization (all positions already in meters)
        print("🎨 Generating visualization...")
        viz_bytes = visualize_formation_comparison(
            before_positions, after_positions, ship_names, min_radius_meters
        )
        
        # Save visualization to outputs directory
        outputs_dir = Path(__file__).parent / "outputs"
        outputs_dir.mkdir(exist_ok=True)
        output_file = outputs_dir / f"formation_comparison_{int(min_radius_meters)}m.png"
        with open(output_file, 'wb') as f:
            f.write(viz_bytes)
        
        file_size_kb = len(viz_bytes) / 1024
        print(f"✅ Visualization saved!")
        print(f"   File: {output_file}")
        print(f"   Size: {file_size_kb:.1f} KB")
        print()
        
        # Print statistics
        from formation_optimizer.formation_optimizer import _calculate_formation_stats
        import numpy as np
        
        leader_before = before_positions.get("leader", np.array([0.0, 0.0, 0.0]))
        leader_after = after_positions.get("leader", np.array([0.0, 0.0, 0.0]))
        
        avg_radius_before, avg_spacing_before = _calculate_formation_stats(
            leader_before, ships_before
        )
        avg_radius_after, avg_spacing_after = _calculate_formation_stats(
            leader_after, ships_after
        )
        
        print("📈 Statistics:")
        print(f"   Before Optimization:")
        print(f"     Average Radius: {avg_radius_before:.2f} meters")
        print(f"     Average Spacing: {avg_spacing_before:.2f} meters")
        print(f"   After Optimization:")
        print(f"     Average Radius: {avg_radius_after:.2f} meters")
        print(f"     Average Spacing: {avg_spacing_after:.2f} meters")
        print()
        
        # Generate GIF animation if requested
        if create_gif:
            print("🎬 Generating animation GIF...")
            try:
                outputs_dir = Path(__file__).parent / "outputs"
                outputs_dir.mkdir(exist_ok=True)
                gif_path = create_formation_animation_gif(
                    str(fleet_file),
                    min_distance_meters=min_radius_meters,
                    output_path=str(outputs_dir / f"formation_animation_{int(min_radius_meters)}m.gif"),
                    fps=10,
                    duration_ms=100
                )
                gif_size_kb = os.path.getsize(gif_path) / 1024
                print(f"✅ Animation GIF saved!")
                print(f"   File: {gif_path}")
                print(f"   Size: {gif_size_kb:.1f} KB")
                print()
                
                if open_image:
                    try:
                        import subprocess
                        import platform
                        system = platform.system()
                        if system == "Darwin":  # macOS
                            subprocess.run(["open", gif_path])
                        elif system == "Windows":
                            os.startfile(gif_path)
                        elif system == "Linux":
                            subprocess.run(["xdg-open", gif_path])
                        print(f"🎬 Opened GIF in default viewer")
                    except Exception as e:
                        print(f"⚠️  Could not open GIF automatically: {e}")
            except Exception as e:
                print(f"⚠️  Failed to generate GIF: {e}")
                import traceback
                traceback.print_exc()
                print()
        
        # Optionally open the image
        if open_image:
            try:
                import subprocess
                import platform
                
                system = platform.system()
                if system == "Darwin":  # macOS
                    subprocess.run(["open", str(output_file)])
                elif system == "Windows":
                    os.startfile(str(output_file))
                elif system == "Linux":
                    subprocess.run(["xdg-open", str(output_file)])
                print(f"🖼️  Opened image in default viewer")
            except Exception as e:
                print(f"⚠️  Could not open image automatically: {e}")
                print(f"   Please open manually: {output_file}")
        
        print("✅ Test complete!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Test formation visualization locally",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use default test file with default radius (350m)
  python test_formation_visualization.py
  
  # Use custom fleet file
  python test_formation_visualization.py my_fleet.fleet
  
  # Use custom fleet file and radius (in meters)
  python test_formation_visualization.py my_fleet.fleet 500
  
  # Open image automatically after generation
  python test_formation_visualization.py --open
        """
    )
    
    parser.add_argument(
        "fleet_file",
        nargs="?",
        default=None,
        help="Path to fleet file (default: d0f246ea-66a7-4c83-a11a-120feb24474d.fleet)"
    )
    parser.add_argument(
        "min_radius",
        nargs="?",
        type=float,
        default=350.0,
        help="Minimum radius in meters (default: 350.0)"
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated image automatically"
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        help="Generate animated GIF showing optimization process"
    )
    
    args = parser.parse_args()
    
    success = test_visualization(
        fleet_file=args.fleet_file,
        min_radius_meters=args.min_radius,
        open_image=args.open,
        create_gif=args.gif
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()


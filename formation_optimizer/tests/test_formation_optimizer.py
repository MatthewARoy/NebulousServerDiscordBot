"""
Test cases for formation optimizer and visualization.

Tests the formation optimization and visualization functionality using
the provided fleet file.
"""
import unittest
import os
import sys
import tempfile
import shutil
import xml.etree.ElementTree as ET
import numpy as np
from pathlib import Path

# Add project root to path when running directly
if __name__ == '__main__':
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

from formation_optimizer.formation_optimizer import (
    compact_formation,
    optimize_fleet_file,
    visualize_formation_comparison,
    _draw_sphere
)


class TestFormationOptimizer(unittest.TestCase):
    """Test cases for formation optimization"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        # Path to the test fleet file
        test_data_dir = os.path.join(os.path.dirname(__file__), "data")
        cls.test_fleet_file = os.path.join(test_data_dir, "d0f246ea-66a7-4c83-a11a-120feb24474d.fleet")
        cls.temp_dir = None
        
    def setUp(self):
        """Set up before each test"""
        # Create temporary directory for test outputs
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up after each test"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_fleet_file_exists(self):
        """Test that the fleet file exists"""
        self.assertTrue(
            os.path.exists(self.test_fleet_file),
            f"Test fleet file {self.test_fleet_file} not found"
        )
    
    def test_parse_fleet_file(self):
        """Test parsing the fleet file"""
        tree = ET.parse(self.test_fleet_file)
        root = tree.getroot()
        
        # Check root element
        self.assertEqual(root.tag, "Fleet")
        
        # Check for Name element
        name_elem = root.find("Name")
        self.assertIsNotNone(name_elem, "Fleet file missing <Name> element")
        self.assertIsNotNone(name_elem.text, "Fleet <Name> element has no text")
        
        # Check for Ship elements
        ships = list(root.iter("Ship"))
        self.assertGreater(len(ships), 0, "Fleet file contains no ships")
        
        # Check for InitialFormation elements
        formations_found = False
        for ship in ships:
            if ship.find("InitialFormation") is not None:
                formations_found = True
                break
        self.assertTrue(formations_found, "Fleet file contains no InitialFormation elements")
    
    def test_compact_formation_basic(self):
        """Test basic formation compaction"""
        # Create a simple test formation
        positions = {
            "leader": np.array([0.0, 0.0, 0.0]),
            "ship1": np.array([100.0, 0.0, 0.0]),
            "ship2": np.array([0.0, 100.0, 0.0]),
            "ship3": np.array([0.0, 0.0, 100.0]),
        }
        
        min_distance = 50.0
        optimized = compact_formation(positions, min_distance=min_distance)
        
        # Check that leader is still at origin
        np.testing.assert_array_almost_equal(
            optimized["leader"], 
            np.array([0.0, 0.0, 0.0]),
            decimal=1
        )
        
        # Check that all ships are present
        self.assertIn("leader", optimized)
        self.assertIn("ship1", optimized)
        self.assertIn("ship2", optimized)
        self.assertIn("ship3", optimized)
        
        # Check that ships maintain minimum distance
        ship_positions = [optimized[k] for k in optimized.keys() if k != "leader"]
        for i, pos1 in enumerate(ship_positions):
            for pos2 in ship_positions[i+1:]:
                distance = np.linalg.norm(pos1 - pos2)
                self.assertGreaterEqual(
                    distance, 
                    min_distance * 0.9,  # Allow small tolerance
                    f"Ships too close: {distance} < {min_distance}"
                )
    
    def test_optimize_fleet_file(self):
        """Test optimizing the fleet file"""
        # Copy fleet file to temp directory
        temp_fleet = os.path.join(self.temp_dir, "test_fleet.fleet")
        shutil.copy(self.test_fleet_file, temp_fleet)
        
        min_distance_meters = 350.0  # User-facing: 350 meters
        
        # Optimize the fleet file
        result = optimize_fleet_file(temp_fleet, min_distance_meters=min_distance_meters)
        
        # Check return value structure
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 4)
        
        optimized_path, before_positions, after_positions, ship_names = result
        
        # Check that optimized file exists
        self.assertTrue(os.path.exists(optimized_path), "Optimized file not created")
        
        # Check that before and after positions are dictionaries
        self.assertIsInstance(before_positions, dict)
        self.assertIsInstance(after_positions, dict)
        self.assertIsInstance(ship_names, dict)
        
        # Check that leader is present
        self.assertIn("leader", before_positions)
        self.assertIn("leader", after_positions)
        
        # Check that leader is at origin
        np.testing.assert_array_almost_equal(
            before_positions["leader"],
            np.array([0.0, 0.0, 0.0]),
            decimal=1
        )
        np.testing.assert_array_almost_equal(
            after_positions["leader"],
            np.array([0.0, 0.0, 0.0]),
            decimal=1
        )
        
        # Check that ship names are populated
        self.assertGreater(len(ship_names), 0, "Ship names dictionary is empty")
        
        # Check that optimized file is valid XML
        tree = ET.parse(optimized_path)
        root = tree.getroot()
        self.assertEqual(root.tag, "Fleet")
        
        # Check that optimized file has updated name (should contain meters value)
        name_elem = root.find("Name")
        self.assertIsNotNone(name_elem)
        self.assertIn("Optimized", name_elem.text)
        self.assertIn(str(int(min_distance_meters)), name_elem.text)
    
    def test_optimize_fleet_file_small_radius(self):
        """Test optimizing with a small minimum radius"""
        temp_fleet = os.path.join(self.temp_dir, "test_fleet.fleet")
        shutil.copy(self.test_fleet_file, temp_fleet)
        
        min_distance_meters = 100.0  # User-facing: 100 meters
        
        optimized_path, before_positions, after_positions, ship_names = optimize_fleet_file(
            temp_fleet, min_distance_meters=min_distance_meters
        )
        
        # Check that optimization completed
        self.assertTrue(os.path.exists(optimized_path))
        
        # Check that positions changed (formation was optimized)
        ships_before = {k: v for k, v in before_positions.items() if k != "leader"}
        ships_after = {k: v for k, v in after_positions.items() if k != "leader"}
        
        # At least some positions should have changed
        positions_changed = False
        for ship_key in ships_before.keys():
            if ship_key in ships_after:
                if not np.allclose(ships_before[ship_key], ships_after[ship_key], atol=0.1):
                    positions_changed = True
                    break
        
        self.assertTrue(positions_changed, "Formation positions should have changed after optimization")
    
    def test_optimize_fleet_file_large_radius(self):
        """Test optimizing with a large minimum radius"""
        temp_fleet = os.path.join(self.temp_dir, "test_fleet.fleet")
        shutil.copy(self.test_fleet_file, temp_fleet)
        
        min_distance_meters = 1000.0  # User-facing: 1000 meters
        
        optimized_path, before_positions, after_positions, ship_names = optimize_fleet_file(
            temp_fleet, min_distance_meters=min_distance_meters
        )
        
        # Check that optimization completed
        self.assertTrue(os.path.exists(optimized_path))
        
        # Check that ships maintain minimum distance (all positions in meters)
        ships_after = {k: v for k, v in after_positions.items() if k != "leader"}
        ship_positions = list(ships_after.values())
        
        for i, pos1 in enumerate(ship_positions):
            for pos2 in ship_positions[i+1:]:
                distance = np.linalg.norm(pos1 - pos2)
                self.assertGreaterEqual(
                    distance,
                    min_distance_meters * 0.9,  # Allow small tolerance
                    f"Ships too close after optimization: {distance} < {min_distance_meters}"
                )
    
    def test_visualize_formation_comparison(self):
        """Test visualization generation"""
        temp_fleet = os.path.join(self.temp_dir, "test_fleet.fleet")
        shutil.copy(self.test_fleet_file, temp_fleet)
        
        min_distance_meters = 350.0  # User-facing: 350 meters
        
        # Get before and after positions
        _, before_positions, after_positions, ship_names = optimize_fleet_file(
            temp_fleet, min_distance_meters=min_distance_meters
        )
        
        # Generate visualization (all positions already in meters)
        viz_bytes = visualize_formation_comparison(
            before_positions, after_positions, ship_names, min_distance_meters
        )
        
        # Check that visualization was generated
        self.assertIsInstance(viz_bytes, bytes)
        self.assertGreater(len(viz_bytes), 0, "Visualization bytes are empty")
        
        # Check that it's a valid PNG (PNG files start with specific bytes)
        self.assertTrue(viz_bytes.startswith(b'\x89PNG\r\n\x1a\n'), "Visualization is not a valid PNG")
        
        # Save visualization for manual inspection
        viz_path = os.path.join(self.temp_dir, "test_visualization.png")
        with open(viz_path, 'wb') as f:
            f.write(viz_bytes)
        
        self.assertTrue(os.path.exists(viz_path), "Visualization file not saved")
        self.assertGreater(os.path.getsize(viz_path), 0, "Visualization file is empty")
    
    def test_visualize_formation_comparison_empty(self):
        """Test visualization with minimal formation"""
        # Create minimal formation (all positions in meters)
        before_positions = {
            "leader": np.array([0.0, 0.0, 0.0]),
            "ship1": np.array([500.0, 0.0, 0.0]),  # 500 meters
        }
        after_positions = {
            "leader": np.array([0.0, 0.0, 0.0]),
            "ship1": np.array([350.0, 0.0, 0.0]),  # 350 meters
        }
        ship_names = {"ship1": "Test Ship"}
        min_radius_meters = 350.0  # User-facing: 350 meters
        
        # Should not raise an error
        viz_bytes = visualize_formation_comparison(
            before_positions, after_positions, ship_names, min_radius_meters
        )
        
        self.assertIsInstance(viz_bytes, bytes)
        self.assertGreater(len(viz_bytes), 0)
    
    def test_draw_sphere(self):
        """Test sphere drawing function"""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        
        # Test drawing a sphere
        center = np.array([0.0, 0.0, 0.0])
        radius = 10.0
        color = '#00FF00'
        
        # Should not raise an error
        _draw_sphere(ax, center, radius, color, alpha=0.5)
        
        plt.close(fig)
    
    def test_formation_positions_structure(self):
        """Test that formation positions have correct structure"""
        temp_fleet = os.path.join(self.temp_dir, "test_fleet.fleet")
        shutil.copy(self.test_fleet_file, temp_fleet)
        
        _, before_positions, after_positions, ship_names = optimize_fleet_file(
            temp_fleet, min_distance_meters=350.0
        )
        
        # Check that all positions are numpy arrays
        for pos in before_positions.values():
            self.assertIsInstance(pos, np.ndarray)
            self.assertEqual(pos.shape, (3,), "Position should be 3D [x, y, z]")
        
        for pos in after_positions.values():
            self.assertIsInstance(pos, np.ndarray)
            self.assertEqual(pos.shape, (3,), "Position should be 3D [x, y, z]")
        
        # Check that ship names match positions (excluding leader)
        ships_before = {k for k in before_positions.keys() if k != "leader"}
        ships_after = {k for k in after_positions.keys() if k != "leader"}
        
        self.assertEqual(ships_before, ships_after, "Ship sets should match")
        # Ship names may include ships without InitialFormation, so only check that
        # all ships in positions have names
        for ship_key in ships_before:
            self.assertIn(ship_key, ship_names, f"Ship {ship_key} should have a name")
    
    def test_optimize_preserves_ship_count(self):
        """Test that optimization preserves the number of ships"""
        temp_fleet = os.path.join(self.temp_dir, "test_fleet.fleet")
        shutil.copy(self.test_fleet_file, temp_fleet)
        
        _, before_positions, after_positions, ship_names = optimize_fleet_file(
            temp_fleet, min_distance_meters=350.0
        )
        
        ships_before = {k for k in before_positions.keys() if k != "leader"}
        ships_after = {k for k in after_positions.keys() if k != "leader"}
        
        self.assertEqual(
            len(ships_before),
            len(ships_after),
            "Number of ships should be preserved"
        )
        # Ship names may include ships without InitialFormation (like the leader ship),
        # so we only check that all ships in positions have names
        for ship_key in ships_before:
            self.assertIn(ship_key, ship_names, f"Ship {ship_key} should have a name")


def run_visualization_test(fleet_file=None, min_radius_meters=350.0, open_image=False):
    """
    Convenience function to run visualization test locally.
    
    Args:
        fleet_file: Path to fleet file (defaults to test file)
        min_radius_meters: Minimum radius for optimization in METERS (default: 350.0)
        open_image: Whether to open the image automatically (default: False)
    
    Returns:
        Path to generated image file, or None if failed
    """
    import sys
    from pathlib import Path
    
    # Import the visualization test script
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))
    
    from formation_optimizer.tests.test_formation_visualization import test_visualization
    
    if fleet_file is None:
        test_data_dir = Path(__file__).parent / "data"
        fleet_file = test_data_dir / "d0f246ea-66a7-4c83-a11a-120feb24474d.fleet"
    
    success = test_visualization(
        fleet_file=str(fleet_file),
        min_radius_meters=min_radius_meters,
        open_image=open_image
    )
    
    if success:
        output_file = project_root / f"formation_comparison_{int(min_radius_meters)}m.png"
        return str(output_file) if output_file.exists() else None
    return None


if __name__ == '__main__':
    import sys
    
    # If run with --visualization flag, run visualization test instead
    if '--visualization' in sys.argv or '-v' in sys.argv:
        from test_formation_visualization import test_visualization
        test_visualization(open_image='--open' in sys.argv)
    else:
        unittest.main()


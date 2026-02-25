import xml.etree.ElementTree as ET
import numpy as np
import copy
import os
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import io
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    try:
        import imageio
        IMAGEIO_AVAILABLE = True
    except ImportError:
        IMAGEIO_AVAILABLE = False

# Fleet file unit conversion: fleet files use 10-meter increments
# x=35 in fleet file = 350 meters in game
FLEET_UNIT_TO_METERS = 10.0


# -----------------------------
# Formation Optimizer (from earlier)
# -----------------------------
def compact_formation(
    positions,
    min_distance=350.0,
    iterations=500,
    attraction_strength=0.01,
    repulsion_strength=1.0,
    damping=0.9,
    capture_states=False,
):
    """
    Compact formation by optimizing ship positions.
    
    Args:
        positions: Dictionary mapping ship keys to numpy arrays [x, y, z] in METERS
        min_distance: Minimum distance between ships in METERS
        iterations: Number of optimization iterations
        attraction_strength: Strength of attraction to leader
        repulsion_strength: Strength of repulsion between ships
        damping: Velocity damping factor
        capture_states: If True, returns list of intermediate states
    
    Returns:
        If capture_states=False: Final positions dictionary (in METERS)
        If capture_states=True: Tuple of (final_positions, list_of_intermediate_states) (all in METERS)
    """
    ids = list(positions.keys())
    pos = np.array([positions[i] for i in ids], dtype=float)

    leader_idx = ids.index("leader")
    velocity = np.zeros_like(pos)
    min_dist_sq = min_distance ** 2
    
    intermediate_states = []
    if capture_states:
        # Capture initial state
        intermediate_states.append({ids[i]: pos[i].copy() for i in range(len(ids))})

    for iteration in range(iterations):
        forces = np.zeros_like(pos)

        # Pairwise repulsion
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                delta = pos[i] - pos[j]
                dist_sq = np.dot(delta, delta)

                if dist_sq < min_dist_sq and dist_sq > 1e-6:
                    dist = np.sqrt(dist_sq)
                    overlap = min_distance - dist
                    direction = delta / dist
                    force = direction * overlap * repulsion_strength
                    forces[i] += force
                    forces[j] -= force

        # Attraction to leader
        leader_pos = pos[leader_idx]
        for i in range(len(pos)):
            if i == leader_idx:
                continue
            forces[i] += (leader_pos - pos[i]) * attraction_strength

        velocity = (velocity + forces) * damping
        pos += velocity

        pos[leader_idx] = np.zeros(3)
        velocity[leader_idx] = np.zeros(3)
        
        # Capture state at regular intervals
        if capture_states:
            # Capture fewer frames for performance (~20 frames instead of 100)
            # This significantly reduces GIF generation time
            capture_interval = max(1, iterations // 20)  # ~20 frames
            if iteration % capture_interval == 0 or iteration == iterations - 1:
                intermediate_states.append({ids[i]: pos[i].copy() for i in range(len(ids))})

    final_positions = {ids[i]: pos[i] for i in range(len(ids))}
    
    if capture_states:
        return final_positions, intermediate_states
    return final_positions


def _draw_sphere(ax, center, radius, color, alpha=0.3, resolution=20):
    """
    Draw a complete 3D sphere at the given center with the given radius.
    Reduced resolution for better performance while maintaining visual quality.
    """
    u = np.linspace(0, 2 * np.pi, resolution)
    v = np.linspace(0, np.pi, resolution)
    x = radius * np.outer(np.cos(u), np.sin(v)) + center[0]
    y = radius * np.outer(np.sin(u), np.sin(v)) + center[1]
    z = radius * np.outer(np.ones(np.size(u)), np.cos(v)) + center[2]
    # Use basic plot_surface without shading parameter for compatibility
    ax.plot_surface(x, y, z, color=color, alpha=alpha, edgecolor='none', linewidth=0)


def _get_ship_colors(num_ships):
    """
    Generate distinct colors for ships using a color palette.
    
    Args:
        num_ships: Number of ships to generate colors for
    
    Returns:
        List of color hex strings
    """
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    
    # Use a colormap to generate distinct colors
    # Using 'tab20' colormap which has 20 distinct colors
    cmap = cm.get_cmap('tab20')
    colors = []
    for i in range(num_ships):
        # Get color from colormap and convert to hex
        rgba = cmap(i / max(num_ships, 1))
        hex_color = mcolors.rgb2hex(rgba[:3])
        colors.append(hex_color)
    
    return colors


def _calculate_formation_stats(leader_pos, ships):
    """
    Calculate formation statistics: average radius from leader and average spacing between ships.
    
    Args:
        leader_pos: Leader position as numpy array [x, y, z]
        ships: Dictionary mapping ship keys to numpy arrays [x, y, z]
    
    Returns:
        Tuple of (avg_radius, avg_spacing)
    """
    if not ships:
        return 0.0, 0.0
    
    ship_positions = list(ships.values())
    
    # Calculate average radius (distance from leader)
    radii = [np.linalg.norm(pos - leader_pos) for pos in ship_positions]
    avg_radius = np.mean(radii) if radii else 0.0
    
    # Calculate average spacing (distance between ships)
    spacings = []
    for i, pos1 in enumerate(ship_positions):
        for pos2 in ship_positions[i+1:]:
            spacing = np.linalg.norm(pos1 - pos2)
            spacings.append(spacing)
    avg_spacing = np.mean(spacings) if spacings else 0.0
    
    return avg_radius, avg_spacing


def visualize_formation_comparison(before_positions, after_positions, ship_names, min_radius_meters):
    """
    Generate a side-by-side visualization comparing before and after formations.
    
    Args:
        before_positions: Dictionary mapping ship keys to numpy arrays [x, y, z] in METERS
        after_positions: Dictionary mapping ship keys to numpy arrays [x, y, z] in METERS
        ship_names: Dictionary mapping ship keys to display names
        min_radius_meters: Minimum radius for sphere size in METERS
    
    Returns:
        Bytes of the PNG image
    """
    # Create figure with two subplots side by side
    fig = plt.figure(figsize=(16, 8), facecolor='#2F3136')
    
    # Before formation (left)
    ax1 = fig.add_subplot(121, projection='3d')
    ax1.set_facecolor('#2F3136')
    
    # After formation (right)
    ax2 = fig.add_subplot(122, projection='3d')
    ax2.set_facecolor('#2F3136')
    
    # Get leader position (should be at origin)
    leader_pos_before = before_positions.get("leader", np.array([0.0, 0.0, 0.0]))
    leader_pos_after = after_positions.get("leader", np.array([0.0, 0.0, 0.0]))
    
    # Get all ship positions (excluding leader)
    ships_before = {k: v for k, v in before_positions.items() if k != "leader"}
    ships_after = {k: v for k, v in after_positions.items() if k != "leader"}
    
    # Calculate statistics
    avg_radius_before, avg_spacing_before = _calculate_formation_stats(leader_pos_before, ships_before)
    avg_radius_after, avg_spacing_after = _calculate_formation_stats(leader_pos_after, ships_after)
    
    # Calculate bounds for consistent scaling (all in meters)
    all_positions = list(ships_before.values()) + list(ships_after.values())
    if all_positions:
        all_positions = np.array(all_positions)
        max_range = np.max(np.abs(all_positions)) * 1.2  # Add 20% padding
        if max_range < min_radius_meters * 2:
            max_range = min_radius_meters * 2
    else:
        max_range = min_radius_meters * 2
    
    # Colors
    leader_color = '#FFD700'  # Gold for leader
    ship_color = '#00FF00'    # Green for ships
    line_color = '#888888'   # Gray for lines
    
    # Plot before formation
    _plot_formation(ax1, leader_pos_before, ships_before, ship_names, min_radius_meters, 
                    leader_color, ship_color, line_color, max_range, 
                    "Before Optimization", avg_radius_before, avg_spacing_before)
    
    # Plot after formation
    _plot_formation(ax2, leader_pos_after, ships_after, ship_names, min_radius_meters,
                    leader_color, ship_color, line_color, max_range, 
                    "After Optimization", avg_radius_after, avg_spacing_after)
    
    # Overall title
    fig.suptitle('Formation Comparison', color='white', fontsize=16, fontweight='bold', y=0.98)
    
    # Save to bytes
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor='#2F3136', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    
    return buf.getvalue()


def _plot_formation(ax, leader_pos, ships, ship_names, min_radius_meters, leader_color, ship_color, line_color, max_range, title, avg_radius, avg_spacing):
    """
    Helper function to plot a single formation view.
    
    Args:
        ax: Matplotlib 3D axes
        leader_pos: Leader position in METERS
        ships: Dictionary of ship positions in METERS
        ship_names: Dictionary of ship names
        min_radius_meters: Minimum radius in METERS
        leader_color, ship_color, line_color: Colors
        max_range: Maximum range for axes in METERS
        title: Plot title
        avg_radius: Average radius in METERS
        avg_spacing: Average spacing in METERS
    """
    # Set equal aspect ratio
    ax.set_xlim([-max_range, max_range])
    ax.set_ylim([-max_range, max_range])
    ax.set_zlim([-max_range, max_range])
    
    # Draw axes
    axis_length = max_range * 0.8
    ax.plot([0, axis_length], [0, 0], [0, 0], 'r-', linewidth=2, label='X')
    ax.plot([0, 0], [0, axis_length], [0, 0], 'g-', linewidth=2, label='Y')
    ax.plot([0, 0], [0, 0], [0, axis_length], 'b-', linewidth=2, label='Z')
    
    # Add axis labels
    ax.text(axis_length * 1.1, 0, 0, 'X', color='red', fontsize=10, fontweight='bold')
    ax.text(0, axis_length * 1.1, 0, 'Y', color='green', fontsize=10, fontweight='bold')
    ax.text(0, 0, axis_length * 1.1, 'Z', color='blue', fontsize=10, fontweight='bold')
    
    # Draw leader sphere (very faint) - all in meters
    _draw_sphere(ax, leader_pos, min_radius_meters * 0.8, leader_color, alpha=0.05)
    # Draw leader black dot
    ax.scatter([leader_pos[0]], [leader_pos[1]], [leader_pos[2]], 
               c='black', s=50, marker='o', edgecolors='none')
    ax.text(leader_pos[0], leader_pos[1], leader_pos[2] + min_radius_meters * 1.2, 
            'Leader', color='white', fontsize=8, ha='center', weight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))
    
    # Generate unique colors for each ship
    ship_list = list(ships.items())
    ship_colors = _get_ship_colors(len(ship_list))
    
    # Collect ship positions and colors for scatter plot
    ship_positions_list = []
    ship_color_list = []
    
    # Draw ship spheres and lines
    for idx, (ship_key, pos) in enumerate(ship_list):
        pos_array = np.array(pos)
        ship_positions_list.append(pos_array)
        ship_color_list.append(ship_colors[idx])
        
        # Draw dotted line from leader to ship
        ax.plot([leader_pos[0], pos_array[0]], 
                [leader_pos[1], pos_array[1]], 
                [leader_pos[2], pos_array[2]], 
                color=line_color, linestyle='--', linewidth=1, alpha=0.5)
        
        # Draw ship sphere with unique color (extremely faint) - all in meters
        _draw_sphere(ax, pos_array, min_radius_meters, ship_colors[idx], alpha=0.05)
        
        # Add ship name
        ship_name = ship_names.get(ship_key, ship_key)
        # Position text slightly above the sphere
        text_pos = pos_array + np.array([0, 0, min_radius_meters * 1.2])
        ax.text(text_pos[0], text_pos[1], text_pos[2], 
                ship_name, color='white', fontsize=7, ha='center', weight='bold',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='black', alpha=0.7))
    
    # Draw colored dots for all ships (matching sphere colors)
    if ship_positions_list:
        ship_positions_array = np.array(ship_positions_list)
        ax.scatter(ship_positions_array[:, 0], 
                   ship_positions_array[:, 1], 
                   ship_positions_array[:, 2],
                   c=ship_color_list, s=50, marker='o', edgecolors='none', zorder=10)
    
    # Set isometric view (forward-left perspective)
    # Elevation and azimuth for forward-left view
    ax.view_init(elev=20, azim=45)
    
    # Set title with statistics
    title_text = f"{title}\nAvg Radius: {avg_radius:.1f}m | Avg Spacing: {avg_spacing:.1f}m"
    ax.set_title(title_text, color='white', fontsize=11, fontweight='bold', pad=10)
    
    # Style the axes
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor('#40444B')
    ax.yaxis.pane.set_edgecolor('#40444B')
    ax.zaxis.pane.set_edgecolor('#40444B')
    ax.grid(True, color='#40444B', linestyle='--', linewidth=0.5, alpha=0.3)
    
    # Set axis label colors
    ax.tick_params(colors='#DCDDDE', labelsize=8)


def create_formation_animation(
    initial_positions,
    intermediate_states,
    ship_names,
    min_radius_meters,
    output_path=None,
    fps=10,
    duration_ms=100
):
    """
    Create an animated GIF showing the formation optimization process.
    
    Args:
        initial_positions: Dictionary mapping ship keys to numpy arrays [x, y, z] in METERS
        intermediate_states: List of position dictionaries showing intermediate states (in METERS)
        ship_names: Dictionary mapping ship keys to display names
        min_radius_meters: Minimum radius for sphere size in METERS
        output_path: Path to save GIF (default: None, returns bytes)
        fps: Frames per second for animation
        duration_ms: Duration per frame in milliseconds
    
    Returns:
        Bytes of the GIF if output_path is None, otherwise None
    """
    if not PIL_AVAILABLE and not IMAGEIO_AVAILABLE:
        raise ImportError("PIL/Pillow or imageio required for GIF generation. Install with: pip install Pillow")
    
    # Get leader position
    leader_pos = initial_positions.get("leader", np.array([0.0, 0.0, 0.0]))
    
    # Get all ship positions (excluding leader)
    ships_initial = {k: v for k, v in initial_positions.items() if k != "leader"}
    
    # Calculate bounds for consistent scaling
    all_positions = list(ships_initial.values())
    for state in intermediate_states:
        ships_state = {k: v for k, v in state.items() if k != "leader"}
        all_positions.extend(ships_state.values())
    
    if all_positions:
        all_positions = np.array(all_positions)
        max_range = np.max(np.abs(all_positions)) * 1.2
        if max_range < min_radius_meters * 2:
            max_range = min_radius_meters * 2
    else:
        max_range = min_radius_meters * 2
    
    # Colors
    leader_color = '#FFD700'  # Gold for leader
    ship_color = '#00FF00'    # Green for ships
    line_color = '#888888'   # Gray for lines
    
    # Generate frames
    frames = []
    total_states = len(intermediate_states)
    
    print(f"Generating {total_states} animation frames...")
    
    for frame_idx, state in enumerate(intermediate_states):
        # Create figure for this frame (smaller size for faster rendering)
        fig = plt.figure(figsize=(8, 8), facecolor='#2F3136')
        ax = fig.add_subplot(111, projection='3d')
        ax.set_facecolor('#2F3136')
        
        # Get ships for this state
        ships_state = {k: v for k, v in state.items() if k != "leader"}
        leader_state = state.get("leader", leader_pos)
        
        # Calculate stats for this frame
        avg_radius, avg_spacing = _calculate_formation_stats(leader_state, ships_state)
        
        # Plot formation
        _plot_formation(
            ax, leader_state, ships_state, ship_names, min_radius_meters,
            leader_color, ship_color, line_color, max_range,
            f"Optimization Progress ({frame_idx+1}/{total_states})", avg_radius, avg_spacing
        )
        
        # Convert to image (reduced DPI for better performance)
        buf = io.BytesIO()
        # Use lower DPI and optimize settings for speed
        plt.savefig(buf, format='png', facecolor='#2F3136', dpi=72, bbox_inches='tight', 
                   pad_inches=0.1, transparent=False)
        buf.seek(0)
        
        if PIL_AVAILABLE:
            frame = Image.open(buf)
            frames.append(frame.copy())
        else:
            # Use imageio
            import imageio
            frame_data = buf.read()
            frames.append(frame_data)
        
        plt.close(fig)
        
        if (frame_idx + 1) % 10 == 0:
            print(f"  Generated {frame_idx + 1}/{total_states} frames...")
    
    # Add pause at the end: duplicate final frame for ~1 second
    # Use a simpler approach - just duplicate the final frame multiple times
    # This is much faster than regenerating
    if frames:
        pause_frames = int(fps)  # Add 1 second worth of frames (fps frames per second)
        print(f"Adding {pause_frames} pause frames at the end...")
        final_frame = frames[-1]
        
        # For PIL, we need to ensure each frame is a separate object
        # Convert to array and back to create distinct objects
        if PIL_AVAILABLE:
            final_array = np.array(final_frame)
            for _ in range(pause_frames):
                # Create a new image from the array each time
                pause_frame = Image.fromarray(final_array.copy())
                frames.append(pause_frame)
        else:
            # For imageio, just duplicate the data
            for _ in range(pause_frames):
                frames.append(final_frame)
    
    print(f"Creating GIF from {len(frames)} frames...")
    
    # Create GIF
    if PIL_AVAILABLE:
        if output_path:
            frames[0].save(
                output_path,
                save_all=True,
                append_images=frames[1:],
                duration=duration_ms,
                loop=0,
                optimize=True
            )
            return None
        else:
            # Save to bytes
            gif_buf = io.BytesIO()
            frames[0].save(
                gif_buf,
                format='GIF',
                save_all=True,
                append_images=frames[1:],
                duration=duration_ms,
                loop=0,
                optimize=True
            )
            gif_buf.seek(0)
            return gif_buf.getvalue()
    else:
        # Use imageio
        import imageio
        if output_path:
            imageio.mimsave(output_path, frames, fps=fps, loop=0)
            return None
        else:
            gif_buf = io.BytesIO()
            imageio.mimsave(gif_buf, frames, format='GIF', fps=fps, loop=0)
            gif_buf.seek(0)
            return gif_buf.getvalue()


def optimize_fleet_file(fleet_path, min_distance_meters=350.0, capture_animation=False):
    """
    Optimize fleet formation file.
    
    Args:
        fleet_path: Path to fleet file
        min_distance_meters: Minimum distance between ships in METERS (user-facing)
        capture_animation: If True, capture intermediate states for animation
    
    Returns:
        Tuple of (optimized_file_path, before_positions, after_positions, ship_names, [intermediate_states])
        All positions are in METERS for user-facing operations
    """
    tree = ET.parse(fleet_path)
    root = tree.getroot()

    # -----------------------------
    # Rename Fleet Name (use meters in name)
    # -----------------------------
    name_elem = root.find("Name")
    if name_elem is None or not name_elem.text:
        raise ValueError("Fleet <Name> element not found")

    original_name = name_elem.text.rstrip("\n")
    optimized_name = f"{original_name}_Optimized_{int(min_distance_meters)}m"
    name_elem.text = optimized_name

    # -----------------------------
    # Map ships
    # -----------------------------
    ships = {}
    for ship in root.iter("Ship"):
        key = ship.findtext("Key")
        if key:
            ships[key] = ship

    formation_positions = {}
    ship_to_pos_elem = {}
    leader_key = None

    for ship_key, ship in ships.items():
        formation = ship.find("InitialFormation")
        if formation is None:
            continue

        guide = formation.findtext("GuideKey")
        pos_elem = formation.find("RelativePosition")

        if guide is None or pos_elem is None:
            continue

        # Read from fleet file (in 10-meter units) and convert to meters
        x_fleet = float(pos_elem.findtext("x"))
        y_fleet = float(pos_elem.findtext("y"))
        z_fleet = float(pos_elem.findtext("z"))
        
        # Convert fleet units (10m increments) to meters
        x_meters = x_fleet * FLEET_UNIT_TO_METERS
        y_meters = y_fleet * FLEET_UNIT_TO_METERS
        z_meters = z_fleet * FLEET_UNIT_TO_METERS

        if leader_key is None:
            leader_key = guide

        # Store positions in meters for internal calculations
        formation_positions[ship_key] = np.array([x_meters, y_meters, z_meters])
        ship_to_pos_elem[ship_key] = pos_elem

    if leader_key is None:
        raise ValueError("No GuideKey found in InitialFormation")

    # Add leader at origin (in meters)
    formation_positions["leader"] = np.array([0.0, 0.0, 0.0])
    
    # Store before positions (deep copy for visualization) - in meters
    before_positions = {k: np.array(v) for k, v in formation_positions.items()}
    
    # Store ship names for visualization
    ship_names = {}
    for ship_key, ship in ships.items():
        name_elem = ship.find("Name")
        if name_elem is not None and name_elem.text:
            ship_names[ship_key] = name_elem.text.strip()
        else:
            ship_names[ship_key] = ship_key

    # -----------------------------
    # Optimize Formation (all in meters)
    # -----------------------------
    if capture_animation:
        optimized, intermediate_states = compact_formation(
            formation_positions,
            min_distance=min_distance_meters,  # Already in meters
            capture_states=True
        )
    else:
        optimized = compact_formation(
            formation_positions,
            min_distance=min_distance_meters,  # Already in meters
            capture_states=False
        )
        intermediate_states = None

    # -----------------------------
    # Write positions back (convert meters to fleet units)
    # -----------------------------
    for ship_key, pos_meters in optimized.items():
        if ship_key == "leader":
            continue

        # Convert from meters to fleet units (10m increments)
        pos_fleet = pos_meters / FLEET_UNIT_TO_METERS
        
        pos_elem = ship_to_pos_elem[ship_key]
        pos_elem.find("x").text = f"{pos_fleet[0]:.6f}"
        pos_elem.find("y").text = f"{pos_fleet[1]:.6f}"
        pos_elem.find("z").text = f"{pos_fleet[2]:.6f}"

    # -----------------------------
    # Write output file
    # -----------------------------
    base, ext = os.path.splitext(fleet_path)
    out_path = f"{base}_Optimized_{int(min_distance_meters)}m{ext}"

    tree.write(out_path, encoding="utf-8", xml_declaration=True)

    # Return positions in meters for user-facing operations
    if capture_animation:
        return out_path, before_positions, optimized, ship_names, intermediate_states
    else:
        return out_path, before_positions, optimized, ship_names


def create_formation_animation_gif(fleet_path, min_distance_meters=350.0, output_path=None, fps=10, duration_ms=100):
    """
    Convenience function to create an animated GIF of the formation optimization process.
    
    Args:
        fleet_path: Path to fleet file
        min_distance_meters: Minimum distance between ships in METERS
        output_path: Path to save GIF (default: auto-generated)
        fps: Frames per second for animation
        duration_ms: Duration per frame in milliseconds
    
    Returns:
        Path to generated GIF file
    """
    # Optimize with animation capture
    result = optimize_fleet_file(fleet_path, min_distance_meters=min_distance_meters, capture_animation=True)
    
    if len(result) == 5:
        optimized_path, before_positions, after_positions, ship_names, intermediate_states = result
    else:
        # Fallback if capture_animation wasn't used
        optimized_path, before_positions, after_positions, ship_names = result
        # Re-run with animation capture
        result = optimize_fleet_file(fleet_path, min_distance_meters=min_distance_meters, capture_animation=True)
        optimized_path, before_positions, after_positions, ship_names, intermediate_states = result
    
    # Generate output path if not provided
    if output_path is None:
        base, _ = os.path.splitext(fleet_path)
        output_path = f"{base}_animation_{int(min_distance_meters)}m.gif"
    
    # Create animation (all positions already in meters)
    create_formation_animation(
        before_positions,
        intermediate_states,
        ship_names,
        min_distance_meters,
        output_path=output_path,
        fps=fps,
        duration_ms=duration_ms
    )
    
    return output_path


# -----------------------------
# Example CLI Usage
# -----------------------------
if __name__ == "__main__":
    input_file = "/mnt/data/d0f246ea-66a7-4c83-a11a-120feb24474d.fleet"
    output_file, before_pos, after_pos, ship_names = optimize_fleet_file(input_file, min_distance=350.0)
    print("Optimized fleet written to:", output_file)
    
    # Generate visualization
    viz_bytes = visualize_formation_comparison(before_pos, after_pos, ship_names, 350.0)
    with open("formation_comparison.png", "wb") as f:
        f.write(viz_bytes)
    print("Visualization saved to: formation_comparison.png")

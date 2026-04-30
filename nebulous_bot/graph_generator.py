"""
Graph generation utilities for Discord bot statistics visualization.
"""

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Tuple
import io
import logging

logger = logging.getLogger(__name__)


class GraphGenerator:
    """Generate graphs from PlayerSnapshot data for Discord display"""
    
    # Color scheme matching Discord bot theme
    PRIMARY_COLOR = '#00FF00'  # Green (matches EMBED_COLOR)
    SECONDARY_COLOR = '#FF0000'  # Red (matches EMBED_COLOR_NO_SERVERS)
    GRID_COLOR = '#36393F'  # Discord dark theme background
    
    @staticmethod
    def parse_graph_type(args: str) -> Tuple[str, str]:
        """
        Parse graph arguments to determine what to graph.
        
        Returns:
            Tuple of (field_name, display_name)
            
        Examples:
            "players online" -> ("total_players", "Players Online")
            "servers" -> ("total_servers", "Active Servers")
            "lobbies" -> ("open_lobbies", "Open Lobbies")
            "games" -> ("games_in_progress", "Games In Progress")
        """
        args_lower = args.lower().strip()
        
        # Map common phrases to database fields
        mappings = {
            'players': ('total_players', 'Players Online'),
            'players online': ('total_players', 'Players Online'),
            'player count': ('total_players', 'Players Online'),
            'online': ('total_players', 'Players Online'),
            
            'servers': ('total_servers', 'Active Servers'),
            'server count': ('total_servers', 'Active Servers'),
            'active servers': ('total_servers', 'Active Servers'),
            
            'lobbies': ('open_lobbies', 'Open Lobbies'),
            'open lobbies': ('open_lobbies', 'Open Lobbies'),
            'lobby count': ('open_lobbies', 'Open Lobbies'),
            
            'games': ('games_in_progress', 'Games In Progress'),
            'games in progress': ('games_in_progress', 'Games In Progress'),
            'active games': ('games_in_progress', 'Games In Progress'),
        }
        
        # Try exact match first
        if args_lower in mappings:
            return mappings[args_lower]
        
        # Try partial matches
        for key, value in mappings.items():
            if key in args_lower:
                return value
        
        # Default to players online
        return ('total_players', 'Players Online')
    
    @staticmethod
    def create_graph(
        timestamps: List[datetime],
        values: List[float],
        title: str,
        ylabel: str,
        color: str = PRIMARY_COLOR
    ) -> bytes:
        """
        Create a graph image from data points.
        
        Args:
            timestamps: List of datetime objects for x-axis
            values: List of numeric values for y-axis
            title: Graph title
            ylabel: Y-axis label
            color: Line color (hex string)
            
        Returns:
            Bytes of the PNG image
        """
        # Set style for Discord-friendly appearance
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 6), facecolor='#2F3136')  # Discord dark gray
        ax.set_facecolor('#2F3136')
        
        # Plot the data
        ax.plot(timestamps, values, color=color, linewidth=2, marker='o', markersize=3, markerfacecolor=color)
        
        # Fill under the line for better visibility
        ax.fill_between(timestamps, values, alpha=0.3, color=color)
        
        # Formatting
        ax.set_title(title, color='white', fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Time', color='#DCDDDE', fontsize=11)
        ax.set_ylabel(ylabel, color='#DCDDDE', fontsize=11)
        
        # Grid
        ax.grid(True, color='#40444B', linestyle='--', linewidth=0.5, alpha=0.5)
        
        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))  # Show tick every 6 hours
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right', color='#DCDDDE')
        
        # Y-axis styling
        ax.tick_params(colors='#DCDDDE')
        
        # Set y-axis to start at 0 for better visualization
        y_min = min(values) if values else 0
        y_max = max(values) if values else 1
        y_padding = (y_max - y_min) * 0.1 if y_max > y_min else 1
        ax.set_ylim(bottom=max(0, y_min - y_padding), top=y_max + y_padding)
        
        # Tight layout to prevent label cutoff
        plt.tight_layout()
        
        # Save to bytes
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#2F3136', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        
        return buf.getvalue()
    
    @staticmethod
    def generate_graph_image(
        data_points: List[Tuple[datetime, float]],
        field_name: str,
        display_name: str
    ) -> bytes:
        """
        Generate a graph image from PlayerSnapshot data.
        
        Args:
            data_points: List of (timestamp, value) tuples
            field_name: Database field name (for reference)
            display_name: Human-readable name for display
            
        Returns:
            Bytes of the PNG image
        """
        if not data_points:
            # Create empty graph with message
            fig, ax = plt.subplots(figsize=(10, 6), facecolor='#2F3136')
            ax.set_facecolor('#2F3136')
            ax.text(0.5, 0.5, 'No data available for the last week', 
                   ha='center', va='center', color='white', fontsize=14)
            ax.set_title(f'{display_name} - Last 7 Days', color='white', fontsize=14, fontweight='bold')
            buf = io.BytesIO()
            plt.savefig(buf, format='png', facecolor='#2F3136', dpi=100, bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)
            return buf.getvalue()
        
        # Separate timestamps and values
        timestamps = [point[0] for point in data_points]
        values = [point[1] for point in data_points]
        
        # Determine color based on field type
        color = GraphGenerator.PRIMARY_COLOR
        if 'servers' in field_name.lower():
            color = '#3498DB'  # Blue
        elif 'lobbies' in field_name.lower():
            color = '#F39C12'  # Orange
        elif 'games' in field_name.lower():
            color = '#E74C3C'  # Red
        
        title = f'{display_name} - Last 7 Days'
        
        return GraphGenerator.create_graph(timestamps, values, title, display_name, color)


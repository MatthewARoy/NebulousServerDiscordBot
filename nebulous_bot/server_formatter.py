"""
Server display formatting utilities to eliminate code duplication.
Centralizes all server display logic, Discord embed creation, and formatting constants.
"""

import discord
from datetime import datetime
from typing import List, Dict, Optional, Callable
from nebulous_bot.config import Config


class ServerConstants:
    """Constants for server display formatting"""
    
    # Status priority for sorting (lower number = higher priority)
    STATUS_PRIORITY = {
        'lobby': 0,
        'unknown': 1, 
        'in_game': 2
    }
    
    # Regional flag mappings
    REGION_FLAGS = {
        'US': '🇺🇸',
        'EU': '🇪🇺', 
        'AU': '🇦🇺',
        'AS': '🌏'
    }
    
    # Default region flag for unknown regions
    DEFAULT_REGION_FLAG = '🌍'
    
    # Status emojis and text mappings
    STATUS_DISPLAY = {
        'lobby': {
            'emoji': '🟢',
            'text': 'Lobby',
            'text_detailed': 'Open Lobby'
        },
        'in_game': {
            'emoji': '🔴', 
            'text': 'In Game',
            'text_detailed': 'Game In Progress'
        },
        'debrief': {
            'emoji': '🟡',
            'text': 'Debrief', 
            'text_detailed': 'Post-Game Debrief'
        }
    }
    
    # Special indicator emojis
    PASSWORD_EMOJI = "🔒"
    SECURE_EMOJI = "🛡️"
    COMPETITIVE_EMOJI = "🏆"
    AUTOBALANCE_EMOJI = "⚖️"
    RANK_RESTRICTED_EMOJI = "🏅"
    TEST_BRANCH_EMOJI = "🧪"


class ServerFormatter:
    """Utility class for formatting server information in Discord embeds"""
    
    def __init__(self, server_monitor=None):
        """Initialize formatter with optional server monitor for game timing info"""
        self.server_monitor = server_monitor
    
    @staticmethod
    def sort_servers_by_priority(servers: List[Dict]) -> List[Dict]:
        """Sort servers by status priority (lobby first) then by player count"""
        def sort_key(server):
            status = server.get('status', 'unknown')
            priority = ServerConstants.STATUS_PRIORITY.get(status, 1)
            player_count = server.get('players', 0)
            return (priority, -player_count)
        
        return sorted(servers, key=sort_key)
    
    @staticmethod
    def sort_lobbies_by_capacity(servers: List[Dict]) -> List[Dict]:
        """Sort lobby servers by how close they are to starting (fewest needed players first)"""
        def lobby_sort_key(server):
            map_capacity = server.get('map_capacity', 8)
            players = server.get('players', 0)
            needed = max(0, map_capacity - players)
            return (needed, -players)  # Prefer servers closest to starting
        
        return sorted(servers, key=lobby_sort_key)
    
    @staticmethod
    def get_region_flag(region: str) -> str:
        """Get regional flag emoji for a region code"""
        return ServerConstants.REGION_FLAGS.get(
            region.upper() if region else '', 
            ServerConstants.DEFAULT_REGION_FLAG
        )
    
    @staticmethod
    def get_status_emoji(status: str) -> str:
        """Get status emoji for server status"""
        status_info = ServerConstants.STATUS_DISPLAY.get(status, ServerConstants.STATUS_DISPLAY['lobby'])
        return status_info['emoji']
    
    def format_status_text(self, server: Dict, detailed: bool = False, include_game_time: bool = False, 
                          game_start_times: Dict = None) -> str:
        """Format server status text with optional game timing information"""
        status = server.get('status', 'lobby')
        status_info = ServerConstants.STATUS_DISPLAY.get(status, ServerConstants.STATUS_DISPLAY['lobby'])
        
        # Choose between detailed or simple text
        if detailed:
            status_text = status_info['text_detailed']
        else:
            status_text = status_info['text']
        
        # Add emoji prefix
        status_with_emoji = f"{status_info['emoji']} {status_text}"
        
        # Add timing info for in-game and debrief servers if requested and available
        if include_game_time and status in ['in_game', 'debrief'] and game_start_times:
            server_id = server.get('id', server.get('address', ''))
            if server_id:
                transition_info = self._format_state_transition_info(server_id, game_start_times)
                if transition_info:
                    status_with_emoji += f" • {transition_info}"
        
        return status_with_emoji
    
    @staticmethod
    def _get_state_transition_timestamp(server_id: str, game_start_times: Dict) -> Optional[int]:
        """Get Unix timestamp for server state transition, or None if no transition recorded"""
        if server_id not in game_start_times:
            return None
            
        transition_time = game_start_times[server_id].get('transition_time')
        if not transition_time:
            return None
            
        return int(transition_time.timestamp())
    
    @staticmethod
    def _format_state_transition_info(server_id: str, game_start_times: Dict) -> Optional[str]:
        """Format state transition timestamp using Discord format"""
        timestamp = ServerFormatter._get_state_transition_timestamp(server_id, game_start_times)
        if not timestamp:
            return None
            
        # Get current state to determine the appropriate label
        current_state = game_start_times[server_id].get('current_state', 'lobby')
        state_labels = {
            'in_game': 'Started',
            'debrief': 'Debrief began'
        }
        
        label = state_labels.get(current_state, 'Changed')
        return f"{label}: <t:{timestamp}:R>"
    
    @staticmethod
    def format_player_display(server: Dict, show_needed: bool = True) -> str:
        """Format player count display with map capacity context"""
        players = server.get('players', 0)
        map_capacity = server.get('map_capacity', 8)
        server_status = server.get('status', 'lobby')
        
        if show_needed and server_status == 'lobby':
            needed = max(0, map_capacity - players)
            return f"**{players}**/{map_capacity} (+{needed} needed)"
        else:
            return f"**{players}**/{map_capacity}"
    
    @staticmethod
    def get_status_icons(server: Dict) -> List[str]:
        """Get list of status indicator emojis for a server"""
        icons = []
        
        if server.get('has_password'):
            icons.append(ServerConstants.PASSWORD_EMOJI)
        if server.get('secure'):
            icons.append(ServerConstants.SECURE_EMOJI)
        if server.get('is_test_branch', False):
            icons.append(ServerConstants.TEST_BRANCH_EMOJI)
            
        # Add regional flag
        region = server.get('region', 'Unknown')
        region_flag = ServerFormatter.get_region_flag(region)
        icons.append(region_flag)
        
        return icons
    
    @staticmethod
    def get_enhanced_status_icons(server: Dict) -> Dict[str, str]:
        """Get enhanced status indicators including competitive flags"""
        icons = {
            'competitive': ServerConstants.COMPETITIVE_EMOJI if server.get('competitive', False) else "",
            'autobalance': ServerConstants.AUTOBALANCE_EMOJI if server.get('autobalance', False) else "", 
            'rank_restricted': ServerConstants.RANK_RESTRICTED_EMOJI if server.get('rank_restricted', False) else ""
        }
        return icons
    
    def create_server_field_value(self, server: Dict, game_start_times: Dict = None) -> str:
        """Create formatted field value for server embed fields"""
        # Get basic server info
        region = server.get('region', 'Unknown')
        map_name = server.get('map', 'Unknown')
        
        # Format server info
        status_text = self.format_status_text(server, detailed=False, include_game_time=False, game_start_times=game_start_times)
        player_display = self.format_player_display(server, show_needed=True)
        status_icons = self.get_status_icons(server)
        game_mode = server.get('game_mode', 'Standard')
        
        # Add timing info for in-game and debrief states
        status_line = f"{status_text} • {player_display}"
        if server.get('status') in ['in_game', 'debrief'] and game_start_times:
            server_id = server.get('id', server.get('address', ''))
            if server_id:
                transition_info = self._format_state_transition_info(server_id, game_start_times)
                if transition_info:
                    status_line += f" • {transition_info}"
        
        # Build the field value
        field_value = (
            f"{status_line}\n"
            f"**Map:** {map_name}\n"
            f"**Mode:** {game_mode}\n"
        )
        
        # Add version info if server is on test branch
        if server.get('is_test_branch', False):
            version = server.get('version', 'Unknown')
            field_value += f"**Version:** {version} (Test Branch)\n"
        
        field_value += f"**Region:** {region} {' '.join(status_icons)}"
        
        return field_value
    
    def create_server_embed_field(self, server: Dict, game_start_times: Dict = None) -> tuple:
        """Create a complete embed field (name, value, inline) for a server"""
        server_name = server.get('name', 'Unknown')
        status_emoji = self.get_status_emoji(server.get('status', 'lobby'))
        field_name = f"{status_emoji} {server_name}"
        field_value = self.create_server_field_value(server, game_start_times)
        
        return (field_name, field_value, True)
    
    def create_server_list_embed(self, servers: List[Dict], title: str, description: str = None, 
                                max_servers: int = 15, last_update: datetime = None, game_start_times: Dict = None) -> discord.Embed:
        """Create embed for server list commands"""
        # Use Discord's native timestamp feature for clean, localized timestamps
        from datetime import timezone
        
        if not servers:
            return discord.Embed(
                title=title,
                description=description or "No servers found matching your criteria.",
                color=Config.EMBED_COLOR_NO_SERVERS,
                timestamp=last_update or datetime.now(timezone.utc)
            )
        
        embed = discord.Embed(
            title=title,
            description=description or f"Found {len(servers)} servers",
            color=Config.EMBED_COLOR,
            timestamp=last_update or datetime.now(timezone.utc)
        )
        
        # Sort and add server fields
        sorted_servers = self.sort_servers_by_priority(servers)
        display_count = 0
        
        for server in sorted_servers[:max_servers]:
            field_name, field_value, inline = self.create_server_embed_field(server, game_start_times)
            embed.add_field(name=field_name, value=field_value, inline=inline)
            display_count += 1
        
        # Add truncation notice if needed
        if len(sorted_servers) > max_servers:
            embed.add_field(
                name="📋 Note",
                value=f"Showing first {max_servers} of {len(sorted_servers)} servers",
                inline=False
            )
        
        return embed
    
    def create_lobby_list_embed(self, servers: List[Dict], last_update: datetime = None) -> discord.Embed:
        """Create embed for open lobby command"""
        # Use Discord's native timestamp feature for clean, localized timestamps
        from datetime import timezone
        
        if not servers:
            return discord.Embed(
                title=f"🚀 {Config.GAME_NAME} - No Open Lobbies",
                description="All servers are currently full or no servers are available.",
                color=Config.EMBED_COLOR_NO_SERVERS,
                timestamp=last_update or datetime.now(timezone.utc)
            )
        
        embed = discord.Embed(
            title=f"🚀 {Config.GAME_NAME} - Open Lobbies",
            description=f"Found {len(servers)} servers with available slots",
            color=Config.EMBED_COLOR,
            timestamp=last_update or datetime.now(timezone.utc)
        )
        
        # Sort by lobby priority (closest to starting first)
        sorted_servers = self.sort_lobbies_by_capacity(servers)
        
        for server in sorted_servers[:12]:  # Limit for embed size
            field_name, field_value, inline = self.create_server_embed_field(server)
            embed.add_field(name=field_name, value=field_value, inline=inline)
        
        # Add truncation notice if needed
        if len(sorted_servers) > 12:
            embed.add_field(
                name="📋 Note",
                value=f"Showing first 12 of {len(sorted_servers)} open servers",
                inline=False
            )
        
        embed.set_footer(text="🟢 = Open Lobby • These servers are accepting new players right now!")
        return embed
    
    def create_status_embed(self, servers: List[Dict], last_update: datetime = None, game_start_times: Dict = None) -> discord.Embed:
        """Create embed for persistent status monitoring"""
        if not servers:
            embed = discord.Embed(
                title=f"🚀 {Config.GAME_NAME} - Server Status",
                description="No active servers found",
                color=Config.EMBED_COLOR_NO_SERVERS,
                timestamp=last_update or datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"🟢 = Open Lobby • 🔴 = Game In Progress • 🟡 = Debrief • Updates every 30s")
            return embed
        
        # Sort servers for display
        sorted_servers = self.sort_servers_by_priority(servers)
        
        # Calculate statistics
        total_players = sum(server.get('players', 0) for server in sorted_servers)
        open_lobbies = len([s for s in sorted_servers if s.get('status') == 'lobby'])
        
        embed = discord.Embed(
            title=f"🚀 {Config.GAME_NAME} - Live Server Status",
            description=f"**{total_players}** active players • **{len(sorted_servers)}** servers • **{open_lobbies}** open lobbies",
            color=Config.EMBED_COLOR,
            timestamp=last_update or datetime.now(timezone.utc)
        )
        
        # Add server fields
        display_count = 0
        for server in sorted_servers:
            if display_count >= Config.MAX_SERVERS_DISPLAY:
                break
            
            field_name, field_value, inline = self.create_server_embed_field(server, game_start_times)
            embed.add_field(name=field_name, value=field_value, inline=inline)
            display_count += 1
        
        # Add summary statistics
        lobby_servers = len([s for s in sorted_servers if s.get('status') == 'lobby'])
        in_game_servers = len([s for s in sorted_servers if s.get('status') == 'in_game'])
        
        summary_text = (
            f"**Total Active Players:** {total_players}\n"
            f"**Open Lobbies:** {lobby_servers} • **In Progress:** {in_game_servers}"
        )
        
        if display_count < len(sorted_servers):
            summary_text += f"\n*Showing {display_count} of {len(sorted_servers)} servers*"
        
        embed.add_field(
            name="📊 Summary",
            value=summary_text,
            inline=False
        )
        
        # Add footer with status legend and contact info (timestamp is shown automatically by Discord)
        footer_text = f"🟢 = Open Lobby • 🔴 = Game In Progress • 🟡 = Debrief • Updates every 30s • Contact @Davaned for any issues"
        embed.set_footer(text=footer_text)
        
        return embed

import aiohttp
import asyncio
import logging
import ssl
import certifi
from typing import List, Dict, Optional
from nebulous_bot.config import Config

logger = logging.getLogger(__name__)

class SteamAPI:
    def __init__(self):
        self.api_key = Config.STEAM_API_KEY
        self.session = None
        self.stable_version = None  # Set dynamically from ServerMonitor
        
    async def __aenter__(self):
        # Create SSL context for secure connections
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self.session = aiohttp.ClientSession(connector=connector)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
    
    async def get_game_servers(self, limit: int = 100, include_all: bool = False) -> List[Dict]:
        """
        Get game servers for Nebulous: Fleet Command using Steam Web API.
        Uses the GetServerList endpoint and enriches with server rules data.
        
        Args:
            limit: Maximum number of servers to return
            include_all: If True, include all servers (empty, private, with bots). 
                        If False, filter out empty, private, and bot servers.
        """
        if not self.session:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)
        
        try:
            url = "https://api.steampowered.com/IGameServersService/GetServerList/v1/"
            params = {
                'key': self.api_key,
                'filter': f'\\appid\\{Config.NEBULOUS_APP_ID}'
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    servers = await self._parse_server_data_with_rules(data, include_all=include_all)
                    return servers
                else:
                    logger.error(f"Steam API request failed with status {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error fetching server data: {e}")
            return []
    
    async def get_server_info(self, server_address: str) -> Optional[Dict]:
        """Get detailed information about a specific server"""
        if not self.session:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)
        
        try:
            # This would query specific server info
            # Implementation depends on available Steam API endpoints
            url = "https://api.steampowered.com/ISteamApps/GetServersAtAddress/v1/"
            params = {
                'key': self.api_key,
                'addr': server_address
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                    
        except Exception as e:
            logger.error(f"Error fetching server info for {server_address}: {e}")
            
        return None
    
    def _query_server_rules_sync(self, server_address: str) -> Optional[Dict]:
        """
        Blocking server rules query using python-valve.
        Run this in a thread to avoid blocking the event loop.
        """
        try:
            # Fix collections compatibility issue for python-valve
            import collections.abc
            import collections
            if not hasattr(collections, 'Mapping'):
                collections.Mapping = collections.abc.Mapping
            if not hasattr(collections, 'MutableMapping'):
                collections.MutableMapping = collections.abc.MutableMapping
            if not hasattr(collections, 'Sequence'):
                collections.Sequence = collections.abc.Sequence
                
            import valve.source.a2s
            
            if ':' not in server_address:
                return None
            
            host, port = server_address.split(':', 1)
            port = int(port)
            
            # Use valve library to query server rules (same as debug script)
            with valve.source.a2s.ServerQuerier((host, port), timeout=3) as server:
                raw_rules = server.rules()
                
                if not raw_rules:
                    logger.debug(f"No server rules returned for {server_address}")
                    return None
                
                # Check if we have Nebulous-style embedded rules JSON in 'rules' field
                if 'rules' in raw_rules:
                    nebulous_rules_json = raw_rules['rules']
                    parsed_rules = self._parse_nebulous_rules_json(nebulous_rules_json)
                    if parsed_rules:
                        return parsed_rules
                
                # Also check for direct Nebulous rules (fallback)
                direct_rules = self._extract_direct_nebulous_rules(raw_rules)
                if direct_rules:
                    return direct_rules
                
                # Return raw rules as fallback
                return raw_rules
            
        except ImportError:
            logger.warning("python-valve library not available for server rules queries. Install with: pip install python-valve")
            return None
        except Exception as e:
            # Use debug level to avoid noisy logs in normal operation
            logger.debug(f"Error querying server rules for {server_address}: {e}")
            return None

    async def get_server_rules(self, server_address: str) -> Optional[Dict]:
        """
        Query server rules off the main event loop to prevent Discord message delays.
        """
        try:
            # Run the blocking A2S query in a thread with a timeout guard
            return await asyncio.wait_for(
                asyncio.to_thread(self._query_server_rules_sync, server_address),
                timeout=3.5
            )
        except asyncio.TimeoutError:
            logger.debug(f"Server rules query timed out for {server_address}")
        except Exception as e:
            logger.debug(f"Error querying server rules for {server_address}: {e}")
        return None
    
    def _parse_nebulous_rules_json(self, rules_data) -> dict:
        """Parse the Nebulous rules from ServerRules response (from debug script)"""
        try:
            import json
            import ast
            
            # Handle case where rules_data is already a dict (from python-valve)
            if isinstance(rules_data, dict):
                return rules_data
            
            # Handle string format
            if isinstance(rules_data, str):
                if not rules_data or not rules_data.strip():
                    return {}
                
                # Handle both single quotes (Python dict format) and double quotes (JSON)  
                if rules_data.startswith('{') and rules_data.endswith('}'):
                    try:
                        # Try JSON parsing first
                        return json.loads(rules_data.replace("'", '"'))
                    except json.JSONDecodeError:
                        try:
                            # Try Python literal evaluation
                            return ast.literal_eval(rules_data)
                        except (ValueError, SyntaxError):
                            pass
            
            return {}
            
        except Exception as e:
            logger.debug(f"Rules parse error: {e}")
            return {}
    
    def _extract_direct_nebulous_rules(self, raw_rules: dict) -> dict:
        """Extract any direct Nebulous rules from the raw ServerRules response (from debug script)"""
        nebulous_rule_keys = {
            'inprogress', 'submode', 'map', 'competitive', 'autobal', 
            'rankrestricted', 'modded', 'version', 'gamemode', 'modFriendly'
        }
        
        direct_rules = {}
        for key, value in raw_rules.items():
            if key.lower() in nebulous_rule_keys:
                direct_rules[key.lower()] = value
        
        return direct_rules if direct_rules else {}
    
    async def _parse_server_data_with_rules(self, raw_data: Dict, include_all: bool = False) -> List[Dict]:
        """Parse raw Steam API response and enrich with server rules data"""
        servers = []
        
        # Server blacklist - add servers that should be filtered out
        blacklisted_servers = {
        }
        
        try:
            if 'response' in raw_data and 'servers' in raw_data['response']:
                basic_servers = []
                
                for server_data in raw_data['response']['servers']:
                    server_name = server_data.get('name', 'Unknown Server')
                    
                    # Skip blacklisted servers (always skip these)
                    if server_name in blacklisted_servers:
                        continue
                    
                    # Apply filtering only if include_all is False
                    if not include_all:
                        # Skip servers with bots
                        bots = server_data.get('bots', 0)
                        if bots > 0:
                            continue
                        
                        # Skip empty servers (no players)
                        players = server_data.get('players', 0)
                        if players == 0:
                            continue
                        
                        # Skip servers with passwords (private)
                        if self._is_private_server(server_name):
                            continue
                    # When include_all=True, include all servers (with bots, empty, private)
                    # Still get player count for display
                    players = server_data.get('players', 0)
                    
                    # Store basic server data
                    basic_servers.append((server_data, server_name, players))
                
                # Query server rules for each server (with concurrency limit)
                import asyncio
                semaphore = asyncio.Semaphore(3)  # Limit concurrent queries
                
                async def get_server_with_rules(server_data, server_name, players):
                    async with semaphore:
                        try:
                            server_address = server_data.get('addr', '')
                            rules = await self.get_server_rules(server_address)
                            return self._create_enhanced_server_data(server_data, server_name, players, rules)
                        except Exception as e:
                            logger.debug(f"Server rules query failed for {server_address}: {e}")
                            return self._create_enhanced_server_data(server_data, server_name, players, None)
                
                # Execute queries concurrently with timeout
                try:
                    tasks = [get_server_with_rules(sd, sn, p) for sd, sn, p in basic_servers]
                    enhanced_servers = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=10.0  # 10 second timeout for all server rules queries
                    )
                    
                    # Add successful results
                    for server in enhanced_servers:
                        if server is not None and not isinstance(server, Exception):
                            servers.append(server)
                            
                except asyncio.TimeoutError:
                    logger.warning("Server rules queries timed out, using basic server data")
                    # Fallback: create servers without rules data
                    for server_data, server_name, players in basic_servers:
                        server = self._create_enhanced_server_data(server_data, server_name, players, None)
                        if server:
                            servers.append(server)
                        
        except Exception as e:
            logger.error(f"Error parsing server data: {e}")
            
        return servers
    
    def _create_enhanced_server_data(self, server_data: Dict, server_name: str, players: int, rules: Optional[Dict]) -> Dict:
        """Create enhanced server data using Steam API data and server rules"""
        # Parse map information from Steam API first (fallback)
        map_name = server_data.get('map', 'Unknown')
        map_capacity = self._extract_map_capacity(map_name)
        
        # Initialize server data with Steam API info
        server = {
            'id': server_data.get('steamid', ''),
            'name': server_name,
            'address': server_data.get('addr', ''),
            'gameport': server_data.get('gameport', 0),
            'players': players,
            'max_players': server_data.get('max_players', 0),
            'bots': 0,  # Always 0 since we filter out servers with bots
            'map': map_name,
            'map_capacity': map_capacity,
            'version': server_data.get('version', ''),
            'secure': server_data.get('secure', False),
            'dedicated': server_data.get('dedicated', True),
            'region': self._determine_region(server_data.get('addr', ''), server_name),
            'has_password': False,
            'ping': 0,
            
            # Default values that may be overridden by rules
            'game_mode': self._determine_game_mode(server_name, map_name),
            'status': 'lobby',  # Default to lobby
            'submode': 'Unknown',
            'competitive': False,
            'autobalance': False,
            'rank_restricted': False,
            'in_progress': '0'  # Default to lobby
        }
        
        # Enhance with server rules if available
        if rules:
            # Map from rules (more accurate than Steam API map field)
            if 'map' in rules:
                server['map'] = rules['map']
                server['map_capacity'] = self._extract_map_capacity(rules['map'])
            
            # Game state from inprogress rule
            in_progress = rules.get('inprogress', '0')
            server['in_progress'] = in_progress
            
            if in_progress == '0':
                server['status'] = 'lobby'
            elif in_progress == '1':
                server['status'] = 'in_game'
            elif in_progress == '2':
                server['status'] = 'debrief'
            else:
                server['status'] = 'lobby'  # Default
            
            # Submode (actual gamemode)
            server['submode'] = rules.get('submode', 'Unknown')
            
            # Competitive flag
            server['competitive'] = rules.get('competitive', '0') == '1'
            
            # Autobalance
            server['autobalance'] = rules.get('autobal', '0') == '1'
            
            # Rank restrictions
            server['rank_restricted'] = rules.get('rankrestricted', '0') == '1'
            
            # Version from rules (prefer rules over Steam API)
            # Check case-insensitively since rules might come from different sources
            version_key = None
            for key in rules.keys():
                if key.lower() == 'version':
                    version_key = key
                    break
            if version_key:
                server['version'] = rules[version_key]
            
            # Update game_mode based on competitive flag and submode
            if server['competitive']:
                server['game_mode'] = f"Competitive {server['submode']}"
            else:
                server['game_mode'] = f"Casual {server['submode']}"
        
        # Detect if server is on test branch (ahead of stable version)
        server['is_test_branch'] = self._is_test_branch_server(server.get('version', ''))
        
        # Set status emoji based on server status
        if server['status'] == 'lobby':
            server['status_emoji'] = '🟢'  # Green - lobby open
        elif server['status'] == 'in_game':
            server['status_emoji'] = '🔴'  # Red - game in progress
        elif server['status'] == 'debrief':
            server['status_emoji'] = '🟡'  # Yellow - post-game debrief
        else:
            server['status_emoji'] = '🟢'  # Default to green (lobby)
        
        return server
    
    def _is_private_server(self, server_name: str) -> bool:
        """Determine if a server is private based on name patterns"""
        private_indicators = [
            'password',
            'private',
            'clan only',
            'members only',
            'whitelist'
        ]
        
        name_lower = server_name.lower()
        return any(indicator in name_lower for indicator in private_indicators)
    
    def _extract_map_capacity(self, map_name: str) -> int:
        """Extract player capacity from map name like 'Arroyo (8P)' -> 8"""
        try:
            import re
            # Look for pattern like (8P) or (10P)
            match = re.search(r'\((\d+)P\)', map_name)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        
        # Default capacities for known maps if pattern parsing fails
        map_defaults = {
            'arroyo': 8, 'pillars': 8, 'yukon': 8, 'honeycomb': 8,
            'tumbleweed': 8, 'caltrop': 8, 'tombstones': 8, 'breach': 8,
            'colosseum': 8, 'luna': 8, 'the belt': 8, 'shattered giant': 8,
            'salar': 10, 'ralas': 10, 'styx': 8, 'giant coral': 10,
            'singularity': 10, 'broken spirit l': 10
        }
        
        map_lower = map_name.lower()
        for known_map, capacity in map_defaults.items():
            if known_map in map_lower:
                return capacity
        
        return 8  # Default assumption for unknown maps
    
    # Region tokens found in server names, checked when IP-range lookup fails.
    # The official ERI servers tag their names ("(US EAST)", "(US WEST)"),
    # which survives the server moving hosts — unlike hardcoded IP ranges.
    _REGION_NAME_PATTERNS = [
        ('US', [r'US\s*EAST', r'US\s*WEST', r'\bUSA?\b', r'\bNA\b']),
        ('EU', [r'\bEU\b', r'EUROPE', r'\bEUR\b']),
        ('AU', [r'AUSTRALIA', r'\bAUS\b', r'\bAU\b', r'OCEANIA', r'\bOCE\b']),
        ('AS', [r'\bASIA\b', r'\bSEA\b', r'\bSGP\b', r'\bSG\b', r'JAPAN', r'JPN', r'\bJP\b', r'\bCN\b', r'CHINA']),
    ]

    def _determine_region(self, address: str, name: str = '') -> str:
        """Determine server region from IP address, falling back to the name.

        IP ranges are authoritative when they match, but Nebulous servers
        periodically change hosts (which silently broke region detection for
        the official ERI servers). When the IP doesn't resolve, parse a region
        tag out of the server name as a backstop.
        """
        region = self._determine_region_from_ip(address)
        if region == 'Unknown':
            region = self._determine_region_from_name(name)
        return region

    def _determine_region_from_ip(self, address: str) -> str:
        """Determine server region from known Nebulous IP ranges."""
        if not address:
            return 'Unknown'

        # Common Nebulous server IP ranges
        if address.startswith('207.174.97.') or address.startswith('23.132.156.'):
            return 'US'
        elif address.startswith('37.27.') or address.startswith('5.75.') or address.startswith('87.106.'):
            return 'EU'
        elif address.startswith('51.161.140.'):
            return 'AU'
        elif address.startswith('116.230.') or address.startswith('27.154.'):
            return 'AS'
        else:
            return 'Unknown'

    def _determine_region_from_name(self, name: str) -> str:
        """Parse a region tag (e.g. "US EAST", "EU", "JPN") out of a server name."""
        if not name:
            return 'Unknown'

        import re
        upper = name.upper()
        for code, patterns in self._REGION_NAME_PATTERNS:
            if any(re.search(pattern, upper) for pattern in patterns):
                return code
        return 'Unknown'
    
    def _compare_versions(self, version1: str, version2: str) -> int:
        """
        Compare two semantic versions (x.y.z format).
        Returns: -1 if version1 < version2, 0 if equal, 1 if version1 > version2
        """
        def parse_version(v: str) -> list:
            """Parse version string into list of integers"""
            parts = []
            for part in v.split('.'):
                try:
                    parts.append(int(part))
                except ValueError:
                    # If part is not numeric, try to extract number
                    import re
                    match = re.search(r'\d+', part)
                    if match:
                        parts.append(int(match.group()))
                    else:
                        parts.append(0)
            return parts
        
        try:
            v1_parts = parse_version(version1)
            v2_parts = parse_version(version2)
            
            # Pad shorter version with zeros
            max_len = max(len(v1_parts), len(v2_parts))
            v1_parts.extend([0] * (max_len - len(v1_parts)))
            v2_parts.extend([0] * (max_len - len(v2_parts)))
            
            # Compare parts
            for i in range(max_len):
                if v1_parts[i] < v2_parts[i]:
                    return -1
                elif v1_parts[i] > v2_parts[i]:
                    return 1
            return 0
        except Exception:
            # If comparison fails, return 0 (equal) to be conservative
            return 0
    
    def set_stable_version(self, stable_version: str):
        """Set the stable version (called from ServerMonitor when determined)"""
        self.stable_version = stable_version
    
    def _is_test_branch_server(self, version: str) -> bool:
        """
        Determine if a server is on the test branch (ahead of stable version).
        Test branch servers have version numbers that are ahead of the stable release.
        
        The stable version is determined dynamically from the majority of servers
        when a new daily status message is created.
        """
        if not version or not version.strip():
            return False
        
        version = version.strip()
        
        # If stable version hasn't been determined yet, can't detect test branch
        if not self.stable_version:
            return False
        
        # Compare server version with stable version
        # If server version is higher, it's on test branch
        comparison = self._compare_versions(version, self.stable_version)
        return comparison > 0
    
    def _determine_game_mode(self, server_name: str, map_name: str) -> str:
        """Determine game mode from server name and map"""
        name_lower = server_name.lower()
        
        if 'competitive' in name_lower or 'stack' in name_lower:
            return 'Competitive'
        elif 'casual' in name_lower:
            return 'Casual'
        elif 'new player' in name_lower or 'beginner' in name_lower:
            return 'New Player'
        elif 'modded' in name_lower or 'mod' in name_lower:
            return 'Modded'
        elif 'arena' in name_lower or 'fight club' in name_lower:
            return 'Arena'
        else:
            return 'Standard'

class MockSteamAPI(SteamAPI):
    """Mock Steam API for testing purposes"""
    
    async def get_game_servers(self, limit: int = 100) -> List[Dict]:
        """Return mock server data for testing"""
        import random
        
        mock_servers = []
        server_names = [
            "Nebulous Combat Arena",
            "Fleet Command Central",
            "Tactical Warfare Server",
            "Combat Training Ground",
            "Elite Fleet Battle",
            "Nebulous Skirmish Zone"
        ]
        
        maps = ["Asteroid Field", "Deep Space", "Binary System", "Nebula Cluster", "Station Perimeter"]
        
        for i in range(random.randint(3, 8)):
            players = random.randint(0, 16)
            max_players = random.choice([8, 12, 16, 20])
            
            server = {
                'name': random.choice(server_names) + f" #{i+1}",
                'address': f"192.168.1.{100+i}:27015",
                'players': players,
                'max_players': max_players,
                'map': random.choice(maps),
                'game_mode': random.choice(["Conquest", "Elimination", "Escort", "Defense"]),
                'has_password': random.choice([True, False]),
                'version': "1.4.2",
                'ping': random.randint(20, 200),
                'secure': True
            }
            mock_servers.append(server)
            
        return mock_servers 
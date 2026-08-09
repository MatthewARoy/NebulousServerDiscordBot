import aiohttp
import asyncio
import logging
import socket
import ssl
import struct
import certifi
from typing import List, Dict, Optional, Tuple
from nebulous_bot.config import Config

logger = logging.getLogger(__name__)

# A2S_INFO query payload (Source engine standard).
A2S_INFO_QUERY = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"

class SteamAPI:
    def __init__(self):
        self.api_key = Config.STEAM_API_KEY
        self.session = None
        self.stable_version = None  # Set dynamically from ServerMonitor
        
    async def close(self):
        """Close the persistent HTTP session (call on shutdown)."""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    async def get_game_servers(self) -> List[Dict]:
        """
        Get ALL game servers for Nebulous: Fleet Command using Steam Web API,
        enriched with A2S server-rules data (real game state, map, mods).

        Returns the unfiltered list; callers that want the default display
        set (no empty/bot/private servers) filter with passes_default_filter.
        The HTTP session is created lazily and reused across calls — one
        session for the life of the bot instead of one per poll cycle.
        """
        if not self.session or self.session.closed:
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
                    servers = await self._parse_server_data_with_rules(data)
                    return servers
                else:
                    logger.error(f"Steam API request failed with status {response.status}")
                    return []

        except Exception as e:
            logger.error(f"Error fetching server data: {e}")
            return []

    def passes_default_filter(self, server: Dict) -> bool:
        """Default visibility filter: hide empty, bot-hosting, and private
        servers. Applied to enhanced server dicts from get_game_servers."""
        if server.get('bots', 0) > 0:
            return False
        if server.get('players', 0) == 0:
            return False
        if self._is_private_server(server.get('name', '')):
            return False
        return True
    
    @staticmethod
    def parse_a2s_info_response(data: bytes) -> Optional[Dict]:
        """Parse an A2S_INFO response packet into live server facts.

        Returns {'name', 'map', 'players', 'max_players', 'bots'} or None if
        the packet is not a valid Source-format info response.
        """
        try:
            if len(data) < 6 or data[:4] != b"\xFF\xFF\xFF\xFF" or data[4:5] != b"I":
                return None

            def read_cstring(offset: int) -> Tuple[str, int]:
                end = data.index(b"\x00", offset)
                return data[offset:end].decode("utf-8", "replace"), end + 1

            offset = 6  # skip header (5 bytes) + protocol version byte
            name, offset = read_cstring(offset)
            map_name, offset = read_cstring(offset)
            _folder, offset = read_cstring(offset)
            _game, offset = read_cstring(offset)
            offset += 2  # appid (uint16)
            players, max_players, bots = struct.unpack_from("<BBB", data, offset)
            return {
                'name': name,
                'map': map_name,
                'players': players,
                'max_players': max_players,
                'bots': bots,
            }
        except (ValueError, struct.error):
            return None

    def _query_server_info_sync(self, server_address: str) -> Optional[Dict]:
        """
        Blocking A2S_INFO query with challenge handshake. Run in a thread.

        This is the only live source of the current map and player count:
        the Steam listing lags by minutes (wrong map/population for busy
        servers) and the Nebulous rules payload stopped including 'map'.
        python-valve cannot do this query — servers now demand the
        challenge handshake it predates — hence the raw socket.
        """
        if ':' not in server_address:
            return None
        host, port_str = server_address.split(':', 1)
        try:
            port = int(port_str)
        except ValueError:
            return None

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        try:
            sock.sendto(A2S_INFO_QUERY, (host, port))
            data, _ = sock.recvfrom(4096)
            # 'A' response = server demands a challenge; resend with it.
            if len(data) >= 9 and data[4:5] == b"A":
                sock.sendto(A2S_INFO_QUERY + data[5:9], (host, port))
                data, _ = sock.recvfrom(4096)
            return self.parse_a2s_info_response(data)
        except OSError as e:
            logger.debug(f"A2S_INFO query failed for {server_address}: {e}")
            return None
        finally:
            sock.close()

    def _query_server_state_sync(self, server_address: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Query live info and rules for one server in a single worker thread."""
        info = self._query_server_info_sync(server_address)
        rules = self._query_server_rules_sync(server_address)
        return info, rules

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
            
            # Use valve library to query server rules (same as debug script).
            # 2s so an unreachable server's info+rules attempts together stay
            # inside the 4.5s per-server guard in get_server_state.
            with valve.source.a2s.ServerQuerier((host, port), timeout=2) as server:
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

    async def get_server_state(self, server_address: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        Query live server info and rules off the main event loop to prevent
        Discord message delays. Returns (info, rules); either may be None.
        """
        try:
            # Run the blocking A2S queries in a thread with a timeout guard
            return await asyncio.wait_for(
                asyncio.to_thread(self._query_server_state_sync, server_address),
                timeout=4.5
            )
        except asyncio.TimeoutError:
            logger.debug(f"Server state query timed out for {server_address}")
        except Exception as e:
            logger.debug(f"Error querying server state for {server_address}: {e}")
        return None, None
    
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

                if rules_data.startswith('{') and rules_data.endswith('}'):
                    # Try strict JSON first — swapping quotes before parsing
                    # corrupts payloads containing apostrophes.
                    try:
                        return json.loads(rules_data)
                    except json.JSONDecodeError:
                        pass
                    # Python-literal dicts (single-quoted)
                    try:
                        return ast.literal_eval(rules_data)
                    except (ValueError, SyntaxError):
                        pass
                    # Last resort for malformed mixed-quote payloads
                    try:
                        return json.loads(rules_data.replace("'", '"'))
                    except json.JSONDecodeError:
                        pass

            return {}
            
        except Exception as e:
            logger.debug(f"Rules parse error: {e}")
            return {}
    
    def _extract_direct_nebulous_rules(self, raw_rules: dict) -> dict:
        """Extract any direct Nebulous rules from the raw ServerRules response (from debug script)"""
        nebulous_rule_keys = {
            'inprogress', 'submode', 'map', 'competitive', 'autobal',
            'rankrestricted', 'version', 'gamemode', 'modfriendly', 'modlist'
        }
        
        direct_rules = {}
        for key, value in raw_rules.items():
            if key.lower() in nebulous_rule_keys:
                direct_rules[key.lower()] = value
        
        return direct_rules if direct_rules else {}
    
    async def _parse_server_data_with_rules(self, raw_data: Dict) -> List[Dict]:
        """Parse raw Steam API response and enrich with server rules data"""
        servers = []

        try:
            if 'response' in raw_data and 'servers' in raw_data['response']:
                basic_servers = []

                for server_data in raw_data['response']['servers']:
                    server_name = server_data.get('name', 'Unknown Server')
                    players = server_data.get('players', 0)

                    # No filtering here: all servers are enhanced; display
                    # filtering happens downstream via passes_default_filter.
                    basic_servers.append((server_data, server_name, players))
                
                # Query server rules for each server (with concurrency limit)
                import asyncio
                semaphore = asyncio.Semaphore(3)  # Limit concurrent queries
                
                async def get_server_with_rules(server_data, server_name, players):
                    async with semaphore:
                        try:
                            server_address = server_data.get('addr', '')
                            info, rules = await self.get_server_state(server_address)
                            return self._create_enhanced_server_data(server_data, server_name, players, rules, info)
                        except Exception as e:
                            logger.debug(f"Server state query failed for {server_address}: {e}")
                            return self._create_enhanced_server_data(server_data, server_name, players, None)

                # Execute queries concurrently with timeout
                try:
                    tasks = [get_server_with_rules(sd, sn, p) for sd, sn, p in basic_servers]
                    enhanced_servers = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=15.0  # overall cap for all per-server info+rules queries
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
    
    def _create_enhanced_server_data(self, server_data: Dict, server_name: str, players: int, rules: Optional[Dict], info: Optional[Dict] = None) -> Dict:
        """Create enhanced server data from the Steam listing, live A2S info,
        and server rules.

        The Steam listing lags by minutes, so a live A2S_INFO result (map,
        players, max_players, bots) overrides it. Rules win over both for the
        map if a server ever publishes one again (current builds don't).
        """
        # Parse map information from Steam API first (fallback)
        map_name = server_data.get('map', 'Unknown')

        # Live A2S info beats the stale Steam listing
        if info:
            if info.get('map'):
                map_name = info['map']
            players = info.get('players', players)
        map_capacity = self._extract_map_capacity(map_name)

        # Initialize server data with Steam API info
        server = {
            'id': server_data.get('steamid', ''),
            'name': server_name,
            'address': server_data.get('addr', ''),
            'gameport': server_data.get('gameport', 0),
            'players': players,
            'max_players': (info or {}).get('max_players') or server_data.get('max_players', 0),
            'bots': info.get('bots', server_data.get('bots', 0)) if info else server_data.get('bots', 0),
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
            'is_modded': False,
            'in_progress': '0',  # Default to lobby

            # Name-based (rules never override): the official new-player
            # servers tag their names, same convention as region tags.
            'is_new_player': self._is_new_player_server(server_name),
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

            # Modded: server is running mods if it advertises a non-empty mod list
            server['is_modded'] = self._rules_indicate_modded(rules)

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
    
    # Name tokens marking servers intended for new players. Kept in sync
    # with the heuristics in _determine_game_mode.
    _NEW_PLAYER_NAME_PATTERN = r'new\s*player|beginner|newbie|training'

    @classmethod
    def _is_new_player_server(cls, name: str) -> bool:
        """Whether a server advertises itself as a new-player server."""
        import re
        if not name:
            return False
        return re.search(cls._NEW_PLAYER_NAME_PATTERN, name, re.IGNORECASE) is not None

    @staticmethod
    def _rules_indicate_modded(rules: Optional[Dict]) -> bool:
        """A server is 'modded' when it advertises a non-empty mod list.

        modFriendly=1 only means mods are *permitted*; a non-empty modList
        means mods are actually loaded (full modded gameplay, e.g. MFC). The
        rule key is 'modList' on the JSON path and 'modlist' on the direct
        path, so check both.
        """
        if not rules:
            return False
        mod_list = rules.get('modList') or rules.get('modlist') or ''
        return bool(str(mod_list).strip())

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
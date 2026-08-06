import aiohttp
import asyncio
import logging
import ssl
import certifi
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional
from nebulous_bot.config import Config

logger = logging.getLogger(__name__)

class SteamAPI:
    def __init__(self):
        self.api_key = Config.STEAM_API_KEY
        self.session = None
        self.stable_version = None  # Set dynamically from ServerMonitor
        self._a2s_executor = None

    def _get_a2s_executor(self) -> ThreadPoolExecutor:
        """Dedicated pool for blocking A2S queries.

        Deliberately NOT the asyncio default executor: that one has six
        workers on the production VM and is shared with the statistics
        writer and aiohttp's DNS resolver. A sweep running there would
        occupy the whole pool for most of a cycle and stall both.
        """
        if self._a2s_executor is None:
            self._a2s_executor = ThreadPoolExecutor(
                max_workers=Config.A2S_MAX_CONCURRENCY,
                thread_name_prefix='a2s',
            )
        return self._a2s_executor

    async def close(self):
        """Close the persistent HTTP session (call on shutdown)."""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        if self._a2s_executor is not None:
            # Don't join: a stuck UDP read would block shutdown for seconds.
            self._a2s_executor.shutdown(wait=False)
            self._a2s_executor = None

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

    @staticmethod
    def _log_fallback_coverage(servers: List[Dict]) -> None:
        """Warn when live counts stop working.

        If A2S egress breaks or a game update changes the query protocol,
        every server silently reverts to Steam's stale count — exactly the
        behaviour users complained about — and nothing else would say so at
        production log level.
        """
        if not servers:
            return
        stale = [s['name'] for s in servers if s.get('player_count_source') == 'steam']
        if not stale:
            return
        if len(stale) * 2 >= len(servers):
            logger.warning(
                f"{len(stale)}/{len(servers)} servers fell back to Steam's stale player "
                f"count this cycle — live A2S counts are largely not working. "
                f"Examples: {', '.join(stale[:5])}"
            )
        else:
            logger.debug(
                f"{len(stale)}/{len(servers)} server(s) fell back to Steam's player "
                f"count (A2S unanswered): {', '.join(stale[:5])}"
            )

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
    
    def _query_server_state_sync(self, server_address: str) -> Optional[Dict]:
        """
        Blocking A2S query using python-valve, returning both the parsed
        Nebulous rules and the server's *live* player count:

            {'rules': dict | None, 'player_count': int | None}

        Both halves are queried on one connection and fail independently —
        a server can answer one and not the other.

        Why the count comes from A2S_PLAYER and not from Steam: the
        `players` field on Steam's GetServerList is last-heartbeat data and
        drifts from reality in *both* directions (measured 2026-08-06: one
        ERI server reporting 5 with 2 actually connected, another stuck at
        4 with 8 connected for minutes at a time). A2S_PLAYER is answered
        by the game server itself and is authoritative.

        Why A2S_PLAYER and not the more obvious A2S_INFO: python-valve
        predates the 2020 A2S_INFO challenge requirement, so `info()`
        raises BrokenMessageError ("Invalid value (65) for field
        'response_type'" — 65 is the 'A' challenge reply) against every
        Nebulous server. `players()` implements the challenge flow and
        works.
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

            state = {'rules': None, 'player_count': None}

            # Both queries share one connection; neither failure is fatal.
            #
            # RULES FIRST, deliberately. Rules carry the load-bearing data —
            # status, map, version, modList — and a missing status silently
            # defaults to 'lobby', which advertises an in-progress match as
            # joinable and can fire !nextgame pings. The player count is the
            # nice-to-have. Whichever runs second is what a blown time budget
            # costs us, so the cheap thing goes last.
            with valve.source.a2s.ServerQuerier(
                (host, port), timeout=Config.A2S_SOCKET_TIMEOUT
            ) as server:
                try:
                    state['rules'] = self._parse_rules_response(server.rules(), server_address)
                except Exception as e:
                    logger.debug(f"A2S rules query failed for {server_address}: {e}")

                try:
                    state['player_count'] = self._extract_live_player_count(server.players())
                except Exception as e:
                    logger.debug(f"A2S player query failed for {server_address}: {e}")

            return state

        except ImportError:
            logger.warning("python-valve library not available for A2S queries. Install with: pip install python-valve")
            return None
        except Exception as e:
            # Use debug level to avoid noisy logs in normal operation
            logger.debug(f"Error querying server state for {server_address}: {e}")
            return None

    @staticmethod
    def _extract_live_player_count(players_response) -> Optional[int]:
        """Pull the connected-player count out of an A2S_PLAYER response."""
        if players_response is None:
            return None
        count = players_response.get('player_count')
        if count is None:
            # Defensive only. python-valve decodes the player array using the
            # header count, so with this library the two cannot disagree and
            # a truncated response raises rather than returning a short list.
            # Kept so a future/vendored decoder can't silently return None.
            listed = players_response.get('players')
            count = len(listed) if listed is not None else None
        if count is None:
            return None
        try:
            count = int(count)
        except (TypeError, ValueError):
            return None
        return count if count >= 0 else None

    def _parse_rules_response(self, raw_rules, server_address: str) -> Optional[Dict]:
        """Normalize an A2S_RULES response into the Nebulous rules dict."""
        if not raw_rules:
            logger.debug(f"No server rules returned for {server_address}")
            return None

        # Check if we have Nebulous-style embedded rules JSON in 'rules' field
        if 'rules' in raw_rules:
            parsed_rules = self._parse_nebulous_rules_json(raw_rules['rules'])
            if parsed_rules:
                return parsed_rules

        # Also check for direct Nebulous rules (fallback)
        direct_rules = self._extract_direct_nebulous_rules(raw_rules)
        if direct_rules:
            return direct_rules

        # Return raw rules as fallback
        return raw_rules

    async def get_server_state(self, server_address: str) -> Optional[Dict]:
        """
        Query server rules + live player count off the main event loop to
        prevent Discord message delays. Two A2S round-trips now share the
        budget, hence the wider timeout than the old rules-only query.
        """
        try:
            # Run the blocking A2S query on OUR pool (not asyncio's default
            # executor) with a timeout guard.
            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(
                    self._get_a2s_executor(), self._query_server_state_sync, server_address
                ),
                timeout=Config.A2S_QUERY_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.debug(f"Server state query timed out for {server_address}")
        except Exception as e:
            logger.debug(f"Error querying server state for {server_address}: {e}")
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
                # Matched to the A2S pool size so an admitted task always has
                # a worker waiting: any wider and tasks would burn their
                # A2S_QUERY_TIMEOUT sitting in the executor queue without ever
                # sending a packet, then "fall back" to the stale Steam count
                # this whole path exists to replace.
                semaphore = asyncio.Semaphore(Config.A2S_MAX_CONCURRENCY)
                
                async def get_server_with_rules(server_data, server_name, players):
                    server_address = server_data.get('addr', '')
                    async with semaphore:
                        try:
                            state = await self.get_server_state(server_address) or {}
                            return self._create_enhanced_server_data(
                                server_data, server_name, players,
                                state.get('rules'),
                                live_player_count=state.get('player_count'),
                            )
                        except Exception as e:
                            logger.debug(f"Server state query failed for {server_address}: {e}")
                            return self._create_enhanced_server_data(server_data, server_name, players, None)

                # Execute queries concurrently with timeout
                try:
                    tasks = [get_server_with_rules(sd, sn, p) for sd, sn, p in basic_servers]
                    enhanced_servers = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=20.0  # Whole-sweep budget for rules + player queries
                    )

                    # Add successful results
                    for server in enhanced_servers:
                        if server is not None and not isinstance(server, Exception):
                            servers.append(server)

                    self._log_fallback_coverage(servers)

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
    
    def _create_enhanced_server_data(self, server_data: Dict, server_name: str, players: int,
                                     rules: Optional[Dict],
                                     live_player_count: Optional[int] = None) -> Dict:
        """Create enhanced server data using Steam API data and server rules.

        `live_player_count` is the A2S_PLAYER count when the server answered.
        It supersedes Steam's `players`, which is last-heartbeat data and can
        be wrong in either direction. When A2S didn't answer we keep Steam's
        number rather than zeroing it — a dropped UDP packet must not flicker
        a populated server out of the list (`passes_default_filter` hides
        players == 0).

        A live zero is only believed when `rules` came back too. Zero is the
        one count that removes a server from the filtered cache entirely, and
        that cache is what `_track_game_start_times` watches for the
        in_game -> debrief transition that fires !nextgame notifications and
        closes GameSession rows. A half-answering server (count arrives,
        rules don't) is not good enough evidence to drop a server mid-match;
        rules coming back proves the server is alive and talking.
        """
        # A zero we can't corroborate with rules is treated as no answer.
        if live_player_count == 0 and rules is None:
            logger.debug(
                f"Ignoring uncorroborated zero player count for "
                f"{server_data.get('addr', '')} (rules query also failed)"
            )
            live_player_count = None

        # Parse map information from Steam API first (fallback)
        map_name = server_data.get('map', 'Unknown')
        map_capacity = self._extract_map_capacity(map_name)

        # Initialize server data with Steam API info
        server = {
            'id': server_data.get('steamid', ''),
            'name': server_name,
            'address': server_data.get('addr', ''),
            'gameport': server_data.get('gameport', 0),
            'players': players if live_player_count is None else live_player_count,
            'player_count_source': 'steam' if live_player_count is None else 'a2s',
            'max_players': server_data.get('max_players', 0),
            'bots': server_data.get('bots', 0),
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
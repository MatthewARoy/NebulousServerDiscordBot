#!/usr/bin/env python3
"""
Nebulous: Fleet Command Steam Server Debug Tool

This standalone script tests Steam API server detection for Nebulous: Fleet Command
without requiring Discord bot functionality. It will attempt to find active servers
and dump all available information.

Consider using https://pypi.org/project/python-steam-api/ for steam api
"""

import asyncio
import aiohttp
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional
import ssl
import certifi
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('steam_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SteamServerDebugger:
    def __init__(self):
        self.api_key = os.getenv('STEAM_API_KEY')
        self.nebulous_app_id = 887570  # Nebulous: Fleet Command Steam App ID
        self.session = None
        
        # Set up SSL context
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        self.session = aiohttp.ClientSession(connector=connector)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_steam_web_api_endpoints(self):
        """Test various Steam Web API endpoints for server information"""
        print("=" * 60)
        print("🔍 TESTING STEAM WEB API ENDPOINTS")
        print("=" * 60)
        
        if not self.api_key:
            print("❌ No Steam API key found. Set STEAM_API_KEY in .env file")
            return
        
        endpoints_to_test = [
            {
                'name': 'GetServersAtAddress',
                'url': 'https://api.steampowered.com/ISteamApps/GetServersAtAddress/v1/',
                'params': {'key': self.api_key, 'addr': '0.0.0.0'}
            },
            {
                'name': 'GetServerList (Basic)',
                'url': 'https://api.steampowered.com/IGameServersService/GetServerList/v1/',
                'params': {'key': self.api_key, 'filter': f'\\appid\\{self.nebulous_app_id}'}
            },
            {
                'name': 'GetServerList (Has Players)',
                'url': 'https://api.steampowered.com/IGameServersService/GetServerList/v1/',
                'params': {'key': self.api_key, 'filter': f'\\appid\\{self.nebulous_app_id}\\hasplayers\\1'}
            },
            {
                'name': 'GetServerList (Not Full)',
                'url': 'https://api.steampowered.com/IGameServersService/GetServerList/v1/',
                'params': {'key': self.api_key, 'filter': f'\\appid\\{self.nebulous_app_id}\\notfull\\1'}
            },
            {
                'name': 'GetServerList (Dedicated)',
                'url': 'https://api.steampowered.com/IGameServersService/GetServerList/v1/',
                'params': {'key': self.api_key, 'filter': f'\\appid\\{self.nebulous_app_id}\\dedicated\\1'}
            },
            {
                'name': 'GetAccountList',
                'url': 'https://api.steampowered.com/IGameServersService/GetAccountList/v1/',
                'params': {'key': self.api_key}
            },
            {
                'name': 'GetGameServerPlayerStatsForGame',
                'url': 'https://api.steampowered.com/ISteamGameServerStats/GetGameServerPlayerStatsForGame/v1/',
                'params': {'key': self.api_key, 'appid': self.nebulous_app_id}
            }
        ]
        
        for endpoint in endpoints_to_test:
            await self._test_endpoint(endpoint)
            
        # Now get detailed information about active servers
        await self._analyze_active_servers()
    
    async def _test_endpoint(self, endpoint_info: Dict):
        """Test a specific Steam API endpoint"""
        print(f"\n🚀 Testing: {endpoint_info['name']}")
        print(f"📡 URL: {endpoint_info['url']}")
        print(f"📋 Params: {endpoint_info['params']}")
        
        try:
            async with self.session.get(endpoint_info['url'], params=endpoint_info['params']) as response:
                print(f"📊 Status Code: {response.status}")
                print(f"📝 Headers: {dict(response.headers)}")
                
                if response.status == 200:
                    try:
                        data = await response.json()
                        print(f"✅ Response received:")
                        print(json.dumps(data, indent=2))
                    except Exception as e:
                        text_data = await response.text()
                        print(f"📄 Raw response: {text_data}")
                else:
                    error_text = await response.text()
                    print(f"❌ Error response: {error_text}")
                    
        except Exception as e:
            print(f"💥 Exception occurred: {e}")
    
    async def query_master_server_directly(self):
        """Attempt to query Steam's master server list directly"""
        print("\n" + "=" * 60)
        print("🎯 ATTEMPTING DIRECT MASTER SERVER QUERY")
        print("=" * 60)
        
        # Steam Master Server Query Protocol
        # This is more complex and requires understanding Steam's protocol
        print("📋 Note: Direct master server queries require implementing Steam's")
        print("   binary protocol. This is typically done through libraries like")
        print("   python-valve or direct socket programming.")
        
        try:
            # Try using python-valve if available
            await self._try_valve_query()
        except ImportError:
            print("❌ python-valve not available for direct server queries")
        except Exception as e:
            print(f"💥 Error in direct query: {e}")
    
    async def _try_valve_query(self):
        """Try using python-valve library for server queries"""
        try:
            import valve.source.a2s
            import valve.source.master_server
            
            print("🔧 Using python-valve library for server queries...")
            
            # First, get server list from Steam API to get actual server addresses
            try:
                async with self.session.get(
                    "https://api.steampowered.com/IGameServersService/GetServerList/v1/",
                    params={'key': self.api_key, 'filter': f'\\appid\\{self.nebulous_app_id}'}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        servers = data.get('response', {}).get('servers', [])
                        
                        print(f"🎮 Found {len(servers)} servers from Steam API")
                        
                        # Query ALL non-empty servers for detailed ServerRules
                        non_empty_servers = [s for s in servers if s.get('players', 0) > 0]
                        print(f"\n🎯 Querying ServerRules for {len(non_empty_servers)} non-empty servers:")
                        
                        for i, server in enumerate(non_empty_servers):
                            print(f"\n📍 Server {i+1}/{len(non_empty_servers)}: {server.get('name', 'Unknown')}")
                            print(f"   Players: {server.get('players', 0)}/{server.get('max_players', 0)}")
                            print(f"   Map: {server.get('map', 'Unknown')}")
                            print(f"   Version: {server.get('version', 'Unknown')}")
                            
                            # Query comprehensive server rules using ServerRules API
                            await self._query_comprehensive_server_rules(server.get('addr', ''), server.get('name', 'Unknown'))
                    else:
                        print(f"❌ Steam API request failed: {response.status}")
            except Exception as e:
                print(f"❌ Steam API query failed: {e}")
                    
        except ImportError:
            print("📦 python-valve not installed. Install with: pip install python-valve")
    
    async def _analyze_active_servers(self):
        """Get comprehensive information about all active Nebulous servers"""
        print(f"\n🎮 COMPREHENSIVE NEBULOUS SERVER ANALYSIS")
        print("=" * 60)
        
        try:
            # Get the complete server list
            async with self.session.get(
                "https://api.steampowered.com/IGameServersService/GetServerList/v1/",
                params={'key': self.api_key, 'filter': f'\\appid\\{self.nebulous_app_id}'}
            ) as response:
                if response.status != 200:
                    print(f"❌ Failed to get server list: {response.status}")
                    return
                    
                data = await response.json()
                servers = data.get('response', {}).get('servers', [])
                
                print(f"📊 Found {len(servers)} total Nebulous servers")
                
                # Analyze server distribution
                active_servers = [s for s in servers if s.get('players', 0) > 0]
                full_servers = [s for s in servers if s.get('players', 0) >= s.get('max_players', 1)]
                empty_servers = [s for s in servers if s.get('players', 0) == 0]
                
                print(f"   • {len(active_servers)} servers with players")
                print(f"   • {len(full_servers)} full servers")
                print(f"   • {len(empty_servers)} empty servers")
                
                total_players = sum(s.get('players', 0) for s in servers)
                total_capacity = sum(s.get('max_players', 0) for s in servers)
                
                print(f"   • {total_players} total players online")
                print(f"   • {total_capacity} total server capacity")
                print(f"   • {total_players/total_capacity*100:.1f}% server utilization")
                
                # Regional analysis
                regions = {}
                for server in servers:
                    addr = server.get('addr', '')
                    region = self._guess_region_from_ip(addr)
                    regions[region] = regions.get(region, 0) + 1
                
                print(f"\n🌍 Regional Distribution:")
                for region, count in regions.items():
                    print(f"   • {region}: {count} servers")
                
                # Detailed analysis of active servers
                if active_servers:
                    print(f"\n🔍 DETAILED ANALYSIS OF ACTIVE SERVERS")
                    print("-" * 50)
                    
                    for i, server in enumerate(active_servers):
                        await self._analyze_individual_server(i + 1, server)
                        
        except Exception as e:
            print(f"💥 Server analysis failed: {e}")
    
    def _guess_region_from_ip(self, addr: str) -> str:
        """Guess server region from IP address"""
        if not addr or ':' not in addr:
            return 'Unknown'
            
        ip = addr.split(':')[0]
        
        # Very basic IP-based region guessing
        if ip.startswith('23.132'):
            return 'US East'
        elif ip.startswith('207.174'):
            return 'US West'
        elif ip.startswith('51.161') or ip.startswith('37.27') or ip.startswith('5.'):
            return 'Europe'
        elif ip.startswith('27.154') or ip.startswith('116.230'):
            return 'Asia'
        elif ip.startswith('162.217'):
            return 'Australia'
        else:
            return f'Unknown ({ip})'
    
    async def _analyze_individual_server(self, index: int, server: dict):
        """Perform comprehensive analysis of a single server"""
        name = server.get('name', 'Unknown')
        addr = server.get('addr', 'Unknown')
        players = server.get('players', 0)
        max_players = server.get('max_players', 0)
        map_name = server.get('map', 'Unknown')
        
        print(f"\n🎯 Server {index}: {name}")
        print(f"   📍 Address: {addr}")
        print(f"   👥 Players: {players}/{max_players}")
        print(f"   🗺️  Map: {map_name}")
        print(f"   🌐 Region: {self._guess_region_from_ip(addr)}")
        print(f"   🔒 Security: {'VAC ' if server.get('secure') else ''}{'Dedicated' if server.get('dedicated') else 'Listen'}")
        print(f"   🤖 Bots: {server.get('bots', 0)}")
        print(f"   📦 Version: {server.get('version', 'Unknown')}")
        
        # Try to get comprehensive server information
        await self._query_comprehensive_server_info(addr, name)
    
    async def _query_comprehensive_server_info(self, server_address: str, server_name: str):
        """Get all possible information about a server using valve library"""
        try:
            # Fix collections compatibility issue
            import collections.abc
            import collections
            if not hasattr(collections, 'Mapping'):
                collections.Mapping = collections.abc.Mapping
            if not hasattr(collections, 'MutableMapping'):
                collections.MutableMapping = collections.abc.MutableMapping
            if not hasattr(collections, 'Sequence'):
                collections.Sequence = collections.abc.Sequence
                
            import valve.source.a2s
            
            if ':' in server_address:
                host, port = server_address.split(':')
                port = int(port)
            else:
                host = server_address
                port = 27015
            
            print(f"   🔍 Deep analysis of {host}:{port}")
            
            with valve.source.a2s.ServerQuerier((host, port), timeout=5) as server:
                # Get server info
                try:
                    info = server.info()
                    print(f"   📊 Server Info:")
                    print(f"      Game: {info.game}")
                    print(f"      Server Name: {info.server_name}")
                    print(f"      Map: {info.map_name}")
                    print(f"      Players: {info.player_count}/{info.max_players}")
                    print(f"      Bots: {info.bot_count}")
                    print(f"      Server Type: {info.server_type}")
                    print(f"      Environment: {info.server_os}")
                    print(f"      Visibility: {'Private' if info.visibility else 'Public'}")
                    print(f"      VAC: {'Enabled' if info.vac_enabled else 'Disabled'}")
                    if hasattr(info, 'game_version'):
                        print(f"      Version: {info.game_version}")
                except Exception as e:
                    print(f"   ❌ Could not get server info: {e}")
                
                # Get player list
                try:
                    players = server.players()
                    if players:
                        print(f"   👥 Player List ({len(players)} players):")
                        for player in players:
                            duration_mins = int(player.duration // 60)
                            duration_secs = int(player.duration % 60)
                            print(f"      • {player.name} (Score: {player.score}, Time: {duration_mins}m{duration_secs}s)")
                    else:
                        print("   👥 No players or player list unavailable")
                except Exception as e:
                    print(f"   ❌ Could not get player list: {e}")
                
                # Get server rules (the most important part for Nebulous)
                await self._query_detailed_server_rules(server, server_name)
                
        except ImportError:
            print(f"   📦 python-valve not available for detailed server analysis")
        except Exception as e:
            print(f"   💥 Comprehensive analysis failed: {e}")
    
    async def _query_detailed_server_rules(self, server, server_name: str):
        """Query detailed server rules using Steam Matchmaking Servers ServerRules API"""
        try:
            print(f"   🔍 Querying ServerRules API for {server_name}")
            
            # Get raw server rules using Steam's ServerRules functionality
            raw_rules = server.rules()
            if not raw_rules:
                print("   📋 No server rules returned from ServerRules API")
                return
                
            print(f"   📋 Raw ServerRules Response ({len(raw_rules)} fields):")
            
            # Display all raw rules first
            for key, value in raw_rules.items():
                print(f"      📄 {key}: '{value}'")
            
            # Check if we have the Nebulous-style embedded rules JSON
            if 'rules' in raw_rules:
                nebulous_rules_json = raw_rules['rules']
                print(f"\n   🎮 Found Nebulous Rules JSON String:")
                print(f"      {nebulous_rules_json}")
                
                # Parse the embedded Nebulous rules
                parsed_nebulous_rules = self._parse_nebulous_rules_json(nebulous_rules_json)
                if parsed_nebulous_rules:
                    await self._display_parsed_nebulous_rules(parsed_nebulous_rules, server_name)
                else:
                    print(f"   ❌ Failed to parse Nebulous rules JSON")
            
            # Also check for any direct Nebulous rules (in case format changes)
            direct_nebulous_rules = self._extract_direct_nebulous_rules(raw_rules)
            if direct_nebulous_rules:
                print(f"\n   🎮 Direct Nebulous Rules Found:")
                await self._display_parsed_nebulous_rules(direct_nebulous_rules, server_name)
            
        except Exception as e:
            print(f"   ❌ ServerRules API query failed: {e}")
            import traceback
            print(f"   🔍 Full error: {traceback.format_exc()}")
    
    def _parse_nebulous_rules_json(self, rules_data) -> dict:
        """Parse the Nebulous rules from ServerRules response"""
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
            print(f"   ⚠️  Rules parse error: {e}")
            return {}
    
    def _extract_direct_nebulous_rules(self, raw_rules: dict) -> dict:
        """Extract any direct Nebulous rules from the raw ServerRules response"""
        nebulous_rule_keys = {
            'inprogress', 'submode', 'map', 'competitive', 'autobal', 
            'rankrestricted', 'modded', 'version', 'gamemode', 'modFriendly'
        }
        
        direct_rules = {}
        for key, value in raw_rules.items():
            if key.lower() in nebulous_rule_keys:
                direct_rules[key.lower()] = value
        
        return direct_rules if direct_rules else {}
    
    async def _display_parsed_nebulous_rules(self, nebulous_rules: dict, server_name: str):
        """Display parsed Nebulous rules with comprehensive analysis"""
        print(f"   🎮 Parsed Nebulous Server Rules ({len(nebulous_rules)} rules):")
        
        # Define Nebulous rule interpretations
        rule_interpretations = {
            'inprogress': {
                'description': 'Game State',
                'values': {'0': 'In Lobby', '1': 'Match In Progress', '2': 'Post-Game Debrief'}
            },
            'submode': {
                'description': 'Game Submode',
                'values': {
                    'Control': 'Control Points Mode',
                    'Annihilation': 'Annihilation Mode',
                    'Escort': 'Escort Mode'
                }
            },
            'map': {
                'description': 'Current Map',
                'values': {}
            },
            'competitive': {
                'description': 'Competitive Mode',
                'values': {'0': 'Casual', '1': 'Competitive'}
            },
            'autobal': {
                'description': 'Team Autobalance',
                'values': {'0': 'Disabled', '1': 'Enabled'}
            },
            'rankrestricted': {
                'description': 'Rank Restrictions',
                'values': {'0': 'Open to All Ranks', '1': 'Rank Restricted'}
            },
            'gamemode': {
                'description': 'Game Mode Type',
                'values': {'0': 'Skirmish', '1': 'Conquest'}
            },
            'modFriendly': {
                'description': 'Mod Support',
                'values': {'0': 'Vanilla Only', '1': 'Mods Allowed'}
            },
            'version': {
                'description': 'Game Version',
                'values': {}
            }
        }
        
        # Display each Nebulous rule with interpretation
        for rule_key, rule_value in nebulous_rules.items():
            rule_info = rule_interpretations.get(rule_key, {
                'description': 'Unknown Rule',
                'values': {}
            })
            
            description = rule_info['description']
            interpreted_value = rule_info['values'].get(str(rule_value), str(rule_value))
            
            print(f"      🎯 {rule_key}: '{rule_value}' → {interpreted_value} ({description})")
        
        # Generate comprehensive server state analysis
        await self._generate_server_state_analysis(nebulous_rules, server_name)
    
    async def _generate_server_state_analysis(self, rules: dict, server_name: str):
        """Generate comprehensive analysis of server state from rules"""
        print(f"   🧠 Comprehensive Server State Analysis:")
        
        # Game state analysis
        in_progress = rules.get('inprogress', '0')
        if in_progress == '0':
            status_emoji = "🟢"
            status_text = "In Lobby (accepting players)"
            joinable = True
        elif in_progress == '1':
            status_emoji = "🔴"
            status_text = "Match in progress"
            joinable = False
        elif in_progress == '2':
            status_emoji = "🟡"
            status_text = "Post-game debrief"
            joinable = True
        else:
            status_emoji = "❓"
            status_text = f"Unknown state ({in_progress})"
            joinable = False
        
        print(f"      {status_emoji} Game Status: {status_text}")
        print(f"      {'✅' if joinable else '❌'} Joinable: {'Yes' if joinable else 'No'}")
        
        # Game mode analysis
        submode = rules.get('submode', 'Unknown')
        competitive = rules.get('competitive', '0') == '1'
        gamemode_type = rules.get('gamemode', '1')
        
        mode_category = "Competitive" if competitive else "Casual"
        mode_type = "Conquest" if gamemode_type == '1' else "Skirmish"
        
        print(f"      🎯 Game Mode: {mode_category} {submode} ({mode_type})")
        
        # Server features analysis
        features = []
        if rules.get('autobal', '0') == '1':
            features.append("⚖️ Team Autobalance")
        if rules.get('rankrestricted', '0') == '1':
            features.append("🏅 Rank Restricted")
        if rules.get('modFriendly', '0') == '1':
            features.append("🔧 Mods Allowed")
        
        if features:
            print(f"      ⚙️  Server Features: {', '.join(features)}")
        else:
            print(f"      ⚙️  Server Features: Vanilla configuration")
        
        # Map and capacity analysis
        map_name = rules.get('map', 'Unknown')
        version = rules.get('version', 'Unknown')
        
        print(f"      🗺️  Map: {map_name}")
        if '(' in map_name and 'P)' in map_name:
            try:
                capacity = map_name.split('(')[1].split('P)')[0]
                print(f"      👥 Map Capacity: {capacity} players")
            except:
                pass
        
        print(f"      📦 Game Version: {version}")
        
        # Generate recommendation
        if joinable and not competitive:
            print(f"      💡 Recommendation: Good for casual players!")
        elif joinable and competitive:
            print(f"      💡 Recommendation: Competitive match - bring your A-game!")
        elif not joinable:
            print(f"      💡 Recommendation: Wait for match to finish before joining")
    
    def _interpret_server_state(self, rules: dict, server_name: str):
        """Interpret the current server state based on rules"""
        print(f"   🧠 Server State Interpretation:")
        
        # Game state
        in_progress = rules.get('inprogress', '0')
        if in_progress == '0':
            print(f"      🟢 Status: In Lobby (accepting players)")
        elif in_progress == '1':
            print(f"      🔴 Status: Match in progress")
        elif in_progress == '2':
            print(f"      🟡 Status: Post-game debrief")
        else:
            print(f"      ❓ Status: Unknown ({in_progress})")
        
        # Game mode analysis
        submode = rules.get('submode', 'Unknown')
        competitive = rules.get('competitive', '0') == '1'
        mode_type = "Competitive" if competitive else "Casual"
        print(f"      🎯 Mode: {mode_type} {submode}")
        
        # Server features
        features = []
        if rules.get('autobal', '0') == '1':
            features.append("Autobalance")
        if rules.get('rankrestricted', '0') == '1':
            features.append("Rank Restricted")
        if rules.get('modded', '0') == '1':
            features.append("Modded")
            
        if features:
            print(f"      ⚙️  Features: {', '.join(features)}")
        
        # Map analysis
        map_name = rules.get('map', 'Unknown')
        if '(' in map_name and 'P)' in map_name:
            # Extract player count from map name
            try:
                player_count = map_name.split('(')[1].split('P)')[0]
                print(f"      🗺️  Map Capacity: {player_count} players ({map_name})")
            except:
                print(f"      🗺️  Map: {map_name}")
        else:
            print(f"      🗺️  Map: {map_name}")

    async def _query_comprehensive_server_rules(self, server_address: str, server_name: str):
        """Comprehensive ServerRules API analysis for a single server"""
        try:
            # Fix collections compatibility for python-valve
            import collections.abc
            import collections
            if not hasattr(collections, 'Mapping'):
                collections.Mapping = collections.abc.Mapping
            if not hasattr(collections, 'MutableMapping'):
                collections.MutableMapping = collections.abc.MutableMapping
            if not hasattr(collections, 'Sequence'):
                collections.Sequence = collections.abc.Sequence
                
            import valve.source.a2s
            
            if ':' in server_address:
                host, port = server_address.split(':')
                port = int(port)
            else:
                host = server_address
                port = 27015
            
            print(f"   🔍 Connecting to ServerRules API: {host}:{port}")
            
            with valve.source.a2s.ServerQuerier((host, port), timeout=5) as server:
                # First get basic server info
                try:
                    info = server.info()
                    print(f"   📊 Basic Server Info:")
                    print(f"      Game: {info.game}")
                    print(f"      Environment: {info.server_os}")
                    print(f"      VAC: {'Enabled' if info.vac_enabled else 'Disabled'}")
                    print(f"      Visibility: {'Private' if info.visibility else 'Public'}")
                except Exception as e:
                    print(f"   ⚠️  Basic server info query failed: {e}")
                
                # Now get the detailed server rules - this is the main focus
                await self._query_detailed_server_rules(server, server_name)
                
                # Try to get player list for context
                try:
                    players = server.players()
                    if players and len(players) > 0:
                        print(f"   👥 Active Players ({len(players)}):")
                        for player in players:
                            duration_mins = int(getattr(player, 'duration', 0) // 60)
                            duration_secs = int(getattr(player, 'duration', 0) % 60)
                            score = getattr(player, 'score', 0)
                            name = getattr(player, 'name', 'Unknown')
                            print(f"      • {name} (Score: {score}, Time: {duration_mins}m{duration_secs}s)")
                    else:
                        print(f"   👥 Player list not available or empty")
                except Exception as e:
                    print(f"   ⚠️  Player list query failed: {e}")
                        
        except ImportError:
            print(f"   📦 python-valve library required for ServerRules API access")
            print(f"   💡 Install with: pip install python-valve")
        except Exception as e:
            print(f"   💥 ServerRules API query failed for {server_address}: {e}")
            import traceback
            print(f"   🔍 Detailed error: {traceback.format_exc()}")
    
    async def _query_server_rules(self, server_address: str):
        """Legacy method - now calls comprehensive ServerRules analysis"""
        await self._query_comprehensive_server_rules(server_address, "Server")
    
    async def _query_individual_server(self, server_address):
        """Query an individual server for detailed information"""
        try:
            import valve.source.a2s
            
            host, port = server_address
            
            print(f"  🔍 Querying {host}:{port}")
            
            with valve.source.a2s.ServerQuerier((host, port), timeout=3) as server:
                try:
                    info = server.info()
                    print(f"  📊 Server Info:")
                    print(f"    Name: {info.server_name}")
                    print(f"    Map: {info.map_name}")
                    print(f"    Players: {info.player_count}/{info.max_players}")
                    print(f"    Game: {info.game}")
                    print(f"    Environment: {info.server_os}")
                    
                    # Get player list if server has players
                    if info.player_count > 0:
                        try:
                            players = server.players()
                            print(f"  👥 Players:")
                            for player in players:
                                print(f"    - {player.name} (Score: {player.score}, Time: {player.duration}s)")
                        except Exception as e:
                            print(f"  ❌ Could not get player list: {e}")
                    
                    # Get server rules
                    try:
                        rules = server.rules()
                        print(f"  📜 Server Rules:")
                        for key, value in rules.items():
                            print(f"    {key}: {value}")
                    except Exception as e:
                        print(f"  ❌ Could not get server rules: {e}")
                        
                except Exception as e:
                    print(f"  💥 Failed to query server: {e}")
                    
        except ImportError:
            print("  📦 python-valve required for individual server queries")
    
    async def search_game_tracker_apis(self):
        """Try alternative game tracking APIs"""
        print("\n" + "=" * 60)
        print("🌐 TRYING ALTERNATIVE GAME TRACKER APIS")
        print("=" * 60)
        
        # BattleMetrics API (if available)
        await self._try_battlemetrics_api()
    

    async def _try_battlemetrics_api(self):
        """Try BattleMetrics API"""
        print("🎯 Trying BattleMetrics API...")
        
        try:
            # BattleMetrics has a proper API
            api_url = "https://api.battlemetrics.com/servers"
            params = {
                'filter[game]': 'nebulous',  # Might need different game identifier
                'filter[status]': 'online'
            }
            
            async with self.session.get(api_url, params=params) as response:
                print(f"📊 BattleMetrics Status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    print("✅ BattleMetrics response:")
                    print(json.dumps(data, indent=2))
                else:
                    error_text = await response.text()
                    print(f"❌ BattleMetrics error: {error_text}")
                    
        except Exception as e:
            print(f"💥 BattleMetrics error: {e}")
    
    async def generate_test_report(self):
        """Generate a comprehensive test report"""
        print("\n" + "=" * 60)
        print("📋 GENERATING TEST REPORT")
        print("=" * 60)
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'steam_api_key_present': bool(self.api_key),
            'nebulous_app_id': self.nebulous_app_id,
            'ssl_context_working': True,
            'python_valve_available': False
        }
        
        # Check if python-valve is available
        try:
            import valve
            report['python_valve_available'] = True
        except ImportError:
            pass
        
        print("📊 Test Report:")
        print(json.dumps(report, indent=2))
        
        # Save report to file
        with open('steam_debug_report.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        print("💾 Report saved to: steam_debug_report.json")

async def main():
    """Main debugging function"""
    print("🚀 Nebulous: Fleet Command Steam Server Debugger")
    print(f"⏰ Started at: {datetime.now()}")
    
    async with SteamServerDebugger() as debugger:
        try:
            # Test Steam Web API endpoints
            await debugger.test_steam_web_api_endpoints()
            
            # Try direct master server queries
            await debugger.query_master_server_directly()
            
            # Try alternative APIs
            await debugger.search_game_tracker_apis()
            
            # Generate final report
            await debugger.generate_test_report()
            
        except Exception as e:
            logger.error(f"Debug session failed: {e}")
            print(f"💥 Debug session failed: {e}")
    
    print("\n✅ Debug session completed!")
    print("📄 Check steam_debug.log for detailed logs")
    print("📊 Check steam_debug_report.json for summary")

if __name__ == "__main__":
    # Set SSL environment variables using certifi
    cert_path = certifi.where()
    os.environ['SSL_CERT_FILE'] = cert_path
    os.environ['REQUESTS_CA_BUNDLE'] = cert_path
    os.environ['CURL_CA_BUNDLE'] = cert_path
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Debug session interrupted by user")
    except Exception as e:
        print(f"💥 Fatal error: {e}")
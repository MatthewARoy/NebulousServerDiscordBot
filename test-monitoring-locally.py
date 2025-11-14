#!/usr/bin/env python3
"""
Test script to verify monitoring loop works locally before deploying
Run this to check if the bot connects and monitoring starts
"""

import os
import sys
import asyncio
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nebulous_project.settings')
django.setup()

from nebulous_bot.config import Config
from nebulous_bot.steam_api import SteamAPI

async def test_steam_api():
    """Test Steam API connection"""
    print("🧪 Testing Steam API Connection")
    print("=" * 50)
    
    try:
        Config.validate()
        print("✅ Config validated")
    except Exception as e:
        print(f"❌ Config error: {e}")
        return False
    
    steam_api = SteamAPI()
    
    try:
        async with steam_api as api:
            print("🔍 Fetching servers from Steam API...")
            servers = await api.get_game_servers()
            
            if servers:
                print(f"✅ Found {len(servers)} servers")
                print(f"   Total players: {sum(s.get('players', 0) for s in servers)}")
                
                # Show first 3 servers
                print("\n📋 Sample servers:")
                for i, server in enumerate(servers[:3], 1):
                    print(f"   {i}. {server.get('name', 'Unknown')}")
                    print(f"      Players: {server.get('players', 0)}/{server.get('max_players', 0)}")
                    print(f"      Status: {server.get('status', 'unknown')}")
                    print(f"      Map: {server.get('map', 'unknown')}")
                    print()
                
                return True
            else:
                print("⚠️  No servers found")
                return True  # API works, just no servers
                
    except Exception as e:
        print(f"❌ Steam API error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_monitoring_loop():
    """Test monitoring loop for a few cycles"""
    print("\n🔄 Testing Monitoring Loop")
    print("=" * 50)
    
    from nebulous_bot.server_monitor import ServerMonitor
    from nebulous_bot.server_formatter import ServerFormatter
    
    class MockBot:
        """Mock Discord bot for testing"""
        def __init__(self):
            self.user = type('obj', (object,), {'id': 123456, 'name': 'TestBot'})()
        
        def get_channel(self, channel_id):
            return None  # No actual Discord channel for testing
    
    bot = MockBot()
    monitor = ServerMonitor(bot)
    formatter = ServerFormatter()
    monitor.set_formatter(formatter)
    
    print("📊 Running 3 monitoring cycles...")
    
    for i in range(3):
        print(f"\n🔄 Cycle {i+1}/3:")
        await monitor._update_server_list()
        
        if monitor.cached_servers:
            print(f"   ✅ Cached {len(monitor.cached_servers)} servers")
            print(f"   📅 Last update: {monitor.last_update}")
            open_lobbies = monitor.get_open_lobbies()
            print(f"   🎮 Open lobbies: {len(open_lobbies)}")
        else:
            print(f"   ⚠️  No servers cached")
        
        if i < 2:  # Don't sleep after last iteration
            print(f"   ⏳ Waiting {Config.UPDATE_INTERVAL} seconds...")
            await asyncio.sleep(Config.UPDATE_INTERVAL)
    
    print("\n✅ Monitoring loop test complete!")
    return True

async def main():
    print("🧪 Nebulous Bot Local Testing")
    print("=" * 50)
    print()
    
    # Test 1: Steam API
    steam_ok = await test_steam_api()
    
    if not steam_ok:
        print("\n❌ Steam API test failed. Fix this before deploying.")
        return 1
    
    # Test 2: Monitoring Loop
    try:
        monitor_ok = await test_monitoring_loop()
        
        if monitor_ok:
            print("\n" + "=" * 50)
            print("✅ All tests passed!")
            print("🚀 Bot should work correctly when deployed")
            return 0
        else:
            print("\n❌ Monitoring loop test failed")
            return 1
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)


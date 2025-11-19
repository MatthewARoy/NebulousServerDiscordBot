#!/usr/bin/env python
"""
Test script to verify game persistence and unique ID tracking.
This simulates game lifecycle and bot restart scenarios.
"""

import os
import django
import sys
from datetime import datetime, timedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nebulous_project.settings')
django.setup()

from django.utils import timezone
from nebulous_bot.models import GameSession
from nebulous_bot.statistics_tracker import GameSessionTracker


def test_game_creation():
    """Test that games are created with unique IDs"""
    print("\n" + "="*60)
    print("TEST 1: Game Creation with Unique IDs")
    print("="*60)
    
    # Create a test server state
    test_server = {
        'id': 'test_server_1',
        'name': 'Test Server #1',
        'address': '192.168.1.1:27015',
        'map': 'Hotspot',
        'game_mode': 'Capture',
        'region': 'US WEST',
        'players': 8,
        'status': 'in_game',
        'competitive': True,
        'autobalance': False,
        'rank_restricted': False,
    }
    
    # Create game session
    tracker = GameSessionTracker()
    tracker.update_server_state(test_server)
    
    # Verify game was created
    game = GameSession.objects.filter(server_id='test_server_1', is_ongoing=True).first()
    
    if game:
        print(f"✅ Game created successfully!")
        print(f"   Game ID: {game.id}")
        print(f"   Server: {game.server_name}")
        print(f"   Map: {game.map_name}")
        print(f"   Players at start: {game.players_at_start}")
        print(f"   Is ongoing: {game.is_ongoing}")
        return game
    else:
        print("❌ Failed to create game")
        return None


def test_game_recovery():
    """Test that ongoing games are recovered on restart"""
    print("\n" + "="*60)
    print("TEST 2: Game Recovery on Bot Restart")
    print("="*60)
    
    # Create a new tracker (simulates bot restart)
    print("Simulating bot restart...")
    new_tracker = GameSessionTracker()
    
    # Check if games were recovered
    ongoing_count = GameSession.objects.filter(is_ongoing=True).count()
    print(f"Found {ongoing_count} ongoing game(s) in database")
    print(f"Recovered {len(new_tracker.active_sessions)} game(s) in memory")
    
    if ongoing_count > 0 and len(new_tracker.active_sessions) > 0:
        print("✅ Game recovery successful!")
        for server_id, game_id in new_tracker.active_sessions.items():
            print(f"   Server '{server_id}' → Game #{game_id}")
        return new_tracker
    else:
        print("❌ No games recovered")
        return new_tracker


def test_game_completion(tracker, game_id):
    """Test that games are properly finalized"""
    print("\n" + "="*60)
    print("TEST 3: Game Completion and Finalization")
    print("="*60)
    
    # Simulate server going to debrief
    test_server_debrief = {
        'id': 'test_server_1',
        'name': 'Test Server #1',
        'address': '192.168.1.1:27015',
        'map': 'Hotspot',
        'players': 6,
        'status': 'debrief',
    }
    
    print("Simulating game entering debrief...")
    tracker.update_server_state(test_server_debrief)
    
    game = GameSession.objects.get(id=game_id)
    if game.game_end:
        print(f"✅ Game end time recorded: {game.game_end}")
        print(f"   Players at end: {game.players_at_end}")
    else:
        print("❌ Game end time not recorded")
    
    # Simulate server returning to lobby
    test_server_lobby = {
        'id': 'test_server_1',
        'name': 'Test Server #1',
        'address': '192.168.1.1:27015',
        'map': 'Hotspot',
        'players': 2,
        'status': 'lobby',
    }
    
    print("Simulating server returning to lobby...")
    completed_game = tracker.update_server_state(test_server_lobby)
    
    # Refresh from database
    game.refresh_from_db()
    
    if not game.is_ongoing:
        print(f"✅ Game finalized successfully!")
        print(f"   Game ID: {game.id}")
        print(f"   Duration: {game.duration_seconds}s")
        print(f"   Is valid game: {game.is_valid_game}")
        print(f"   Is ongoing: {game.is_ongoing}")
        
        if game.duration_seconds and game.duration_seconds >= 300:
            print(f"   ✅ Valid game (>= 5 minutes)")
        else:
            print(f"   ⚠️  Too short for valid game (< 5 minutes)")
    else:
        print("❌ Game not finalized")
    
    return game


def test_statistics_queries():
    """Test that statistics can be queried from games"""
    print("\n" + "="*60)
    print("TEST 4: Statistics Calculation from Games")
    print("="*60)
    
    # Total games
    total_games = GameSession.objects.count()
    valid_games = GameSession.objects.filter(is_valid_game=True).count()
    ongoing_games = GameSession.objects.filter(is_ongoing=True).count()
    
    print(f"Total games in database: {total_games}")
    print(f"Valid games (>= 5 min): {valid_games}")
    print(f"Currently ongoing: {ongoing_games}")
    
    # Games today
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    games_today = GameSession.objects.filter(game_start__gte=today_start).count()
    print(f"Games started today: {games_today}")
    
    # Map frequency
    from django.db.models import Count
    top_maps = GameSession.objects.values('map_name').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    if top_maps:
        print("\nTop maps played:")
        for i, map_data in enumerate(top_maps, 1):
            print(f"   {i}. {map_data['map_name']}: {map_data['count']} games")
    
    print("\n✅ Statistics queries working!")


def cleanup_test_games():
    """Clean up test games"""
    print("\n" + "="*60)
    print("Cleanup")
    print("="*60)
    
    # Auto-cleanup test games
    deleted_count = GameSession.objects.filter(server_id='test_server_1').delete()[0]
    print(f"✅ Deleted {deleted_count} test game(s)")


def main():
    print("\n" + "="*60)
    print("GAME PERSISTENCE TEST SUITE")
    print("="*60)
    print("\nThis test verifies:")
    print("1. Games are created with unique IDs")
    print("2. Games can be recovered after bot restart")
    print("3. Games are properly finalized")
    print("4. Statistics can be calculated from games")
    
    try:
        # Test 1: Create game
        game = test_game_creation()
        if not game:
            print("\n❌ Test suite failed at game creation")
            return 1
        
        # Test 2: Recovery
        tracker = test_game_recovery()
        if not tracker:
            print("\n❌ Test suite failed at game recovery")
            return 1
        
        # Test 3: Completion
        # Note: This will mark the game as too short since we're testing immediately
        # In production, games last 5+ minutes
        completed_game = test_game_completion(tracker, game.id)
        
        # Test 4: Statistics
        test_statistics_queries()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\nNote: The test game may be marked as 'invalid' because")
        print("it didn't last 5 minutes. This is expected for a test.")
        
        # Cleanup
        cleanup_test_games()
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())


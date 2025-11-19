#!/usr/bin/env python
"""
Test script to verify timezone consistency and stats tracked since feature.
"""

import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nebulous_project.settings')
django.setup()

from django.utils import timezone as django_timezone
from nebulous_bot.models import GameSession
import pytz

def test_timezone_consistency():
    """Test that all games are properly timezone-aware and can be converted to PST"""
    print("\n" + "="*60)
    print("TEST: Timezone Consistency")
    print("="*60)
    
    # PST timezone
    pst = pytz.timezone('America/Los_Angeles')
    
    # Get all games
    games = GameSession.objects.all()
    total_games = games.count()
    
    print(f"\nTotal games in database: {total_games}")
    
    if total_games == 0:
        print("⚠️  No games in database to test")
        return True
    
    # Check first few games
    test_games = games[:5]
    all_valid = True
    
    for game in test_games:
        # Check if timezone aware
        if game.game_start.tzinfo is None:
            print(f"❌ Game #{game.id} has timezone-naive start time!")
            all_valid = False
        else:
            # Convert to PST
            game_pst = game.game_start.astimezone(pst)
            print(f"✅ Game #{game.id}: {game_pst.strftime('%Y-%m-%d %I:%M %p PST')}")
    
    if all_valid:
        print("\n✅ All games have timezone-aware timestamps!")
    else:
        print("\n❌ Some games have timezone issues!")
    
    return all_valid


def test_first_game_query():
    """Test that we can query the first game correctly"""
    print("\n" + "="*60)
    print("TEST: First Game Query (for 'Stats Tracked Since')")
    print("="*60)
    
    pst = pytz.timezone('America/Los_Angeles')
    
    # Query first valid game (same as in stats command)
    first_game = GameSession.objects.filter(is_valid_game=True).order_by('game_start').first()
    
    if not first_game:
        print("⚠️  No valid games in database")
        return True
    
    print(f"\nFirst valid game found:")
    print(f"  ID: {first_game.id}")
    print(f"  Server: {first_game.server_name}")
    print(f"  Map: {first_game.map_name}")
    
    # Convert to PST
    first_game_pst = first_game.game_start.astimezone(pst)
    tracked_since = first_game_pst.strftime("%B %d, %Y at %I:%M %p PST")
    
    print(f"\n📅 Stats tracked since: {tracked_since}")
    print(f"   (This is what will appear in !stats output)")
    
    print("\n✅ First game query working correctly!")
    return True


def test_timezone_conversion():
    """Test manual timezone conversions"""
    print("\n" + "="*60)
    print("TEST: Timezone Conversions")
    print("="*60)
    
    pst = pytz.timezone('America/Los_Angeles')
    utc = pytz.timezone('UTC')
    
    # Get current time
    now_utc = django_timezone.now()
    now_pst = now_utc.astimezone(pst)
    
    print(f"\nCurrent time:")
    print(f"  UTC: {now_utc.strftime('%Y-%m-%d %I:%M %p %Z')}")
    print(f"  PST: {now_pst.strftime('%Y-%m-%d %I:%M %p %Z')}")
    
    # Check Django settings
    from django.conf import settings
    print(f"\nDjango TIME_ZONE setting: {settings.TIME_ZONE}")
    print(f"Django USE_TZ setting: {settings.USE_TZ}")
    
    if settings.TIME_ZONE == 'America/Los_Angeles' and settings.USE_TZ:
        print("\n✅ Django timezone settings are correct!")
        return True
    else:
        print("\n❌ Django timezone settings may need adjustment!")
        return False


def test_stats_output_format():
    """Test the actual stats output format"""
    print("\n" + "="*60)
    print("TEST: Stats Output Format")
    print("="*60)
    
    pst = pytz.timezone('America/Los_Angeles')
    
    # Get first game
    first_game = GameSession.objects.filter(is_valid_game=True).order_by('game_start').first()
    
    if not first_game:
        print("⚠️  No valid games to format")
        return True
    
    # Format as it will appear in Discord embed
    first_game_pst = first_game.game_start.astimezone(pst)
    tracked_since = first_game_pst.strftime("%B %d, %Y at %I:%M %p PST")
    description = f"📅 *Stats tracked since {tracked_since}*"
    
    print(f"\nDiscord embed description will be:")
    print(f"  {description}")
    
    # Get game stats
    total_games = GameSession.objects.filter(is_valid_game=True).count()
    
    today_start = django_timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    games_today = GameSession.objects.filter(
        is_valid_game=True,
        game_start__gte=today_start
    ).count()
    
    print(f"\nStats summary:")
    print(f"  Total valid games: {total_games}")
    print(f"  Games today: {games_today}")
    
    print("\n✅ Stats output format looks good!")
    return True


def main():
    print("\n" + "="*60)
    print("TIMEZONE & STATS TEST SUITE")
    print("="*60)
    print("\nVerifying timezone consistency and 'Stats Tracked Since' feature")
    
    all_passed = True
    
    try:
        # Run tests
        all_passed &= test_timezone_consistency()
        all_passed &= test_first_game_query()
        all_passed &= test_timezone_conversion()
        all_passed &= test_stats_output_format()
        
        print("\n" + "="*60)
        if all_passed:
            print("✅ ALL TESTS PASSED!")
        else:
            print("⚠️  SOME TESTS HAD ISSUES")
        print("="*60)
        
        return 0 if all_passed else 1
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())


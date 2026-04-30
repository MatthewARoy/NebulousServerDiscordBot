# Game Persistence - Quick Reference

## What Changed?

🎉 **Games now persist across bot restarts!**

Every game gets a unique ID and is saved to the database **immediately when it starts**. If the bot restarts mid-game, it automatically recovers and continues tracking.

## Key Features

### ✅ Unique Game IDs
```python
# Every game has a unique ID
game = GameSession.objects.get(id=42)
print(f"Game #{game.id}: {game.map_name} on {game.server_name}")
```

### ✅ Automatic Recovery
```
[Bot starts]
INFO: Recovered 3 ongoing game(s) from database
```

### ✅ No Data Loss
- Games saved immediately on start
- Survives bot crashes
- Complete game history preserved

## For Developers

### Query Examples

```python
# Get all games
games = GameSession.objects.all()

# Get ongoing games
ongoing = GameSession.objects.filter(is_ongoing=True)

# Get valid games (>= 5 minutes)
valid_games = GameSession.objects.filter(is_valid_game=True)

# Games today
from django.utils import timezone
today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
games_today = GameSession.objects.filter(game_start__gte=today)

# Games on specific server
server_games = GameSession.objects.filter(server_id='server_123')

# Most played maps
from django.db.models import Count
top_maps = GameSession.objects.filter(is_valid_game=True) \
    .values('map_name') \
    .annotate(count=Count('id')) \
    .order_by('-count')[:10]
```

### Game Lifecycle

```python
# 1. Game starts (lobby → in_game)
game = GameSession.objects.create(
    server_id='server_123',
    server_name='My Server',
    map_name='Hotspot',
    game_start=timezone.now(),
    players_at_start=8,
    is_ongoing=True,  # Mark as ongoing
)
# game.id is available immediately (e.g., 42)

# 2. During game (update max players)
game.max_players_during_game = 10
game.save()

# 3. Game ends (in_game → debrief)
game.game_end = timezone.now()
game.players_at_end = 6
game.save()

# 4. Return to lobby (finalize)
game.is_ongoing = False
game.calculate_duration()  # Sets duration_seconds and is_valid_game
game.save()
```

## Testing

### Run Test Suite
```bash
python test_game_persistence.py
```

Expected output:
```
✅ TEST 1: Game Creation with Unique IDs - PASSED
✅ TEST 2: Game Recovery on Bot Restart - PASSED
✅ TEST 3: Game Completion and Finalization - PASSED
✅ TEST 4: Statistics Calculation - PASSED
```

### Manual Testing
```bash
# Check ongoing games
python manage.py shell -c "from nebulous_bot.models import GameSession; print(f'Ongoing: {GameSession.objects.filter(is_ongoing=True).count()}')"

# View recent games
python manage.py shell -c "from nebulous_bot.models import GameSession; for g in GameSession.objects.all()[:5]: print(f'Game #{g.id}: {g.map_name} - {'ongoing' if g.is_ongoing else 'complete'}')"

# Get a specific game
python manage.py shell -c "from nebulous_bot.models import GameSession; g = GameSession.objects.first(); print(f'Game #{g.id}: {g.server_name} on {g.map_name} - {g.duration_seconds}s with {g.players_at_start} players')"
```

## Database Migration

```bash
# Create migration (already done)
python manage.py makemigrations nebulous_bot --name add_is_ongoing_field

# Apply migration
python manage.py migrate

# Verify
python manage.py showmigrations nebulous_bot
```

## Log Examples

### Normal Game
```
INFO: Game #42 started on '[ERI #7] Kribensis': Hotspot with 8 players
INFO: Game #42 entered debrief on '[ERI #7] Kribensis'
INFO: ✅ Game #42 completed on '[ERI #7] Kribensis': Hotspot - 720s with 8 players
```

### Bot Restart Mid-Game
```
[Bot starts]
INFO: Recovered 2 ongoing game(s) from database
INFO: Game #40 entered debrief on '[ERI #3] Molly'
INFO: ✅ Game #40 completed on '[ERI #3] Molly': Crossfire - 540s with 6 players
```

## Discord Commands

All existing commands work unchanged:

```
!stats              - View overall statistics with games today
!stats today        - View today's statistics
!stats week         - View this week's statistics
!mapstats           - View map play frequency
!serverstats        - View server usage statistics
!updatestats        - Force statistics update
```

## Admin Panel

View games in Django admin:

1. Start admin: `python manage.py runserver`
2. Visit: `http://localhost:8000/admin/`
3. Navigate to: **Nebulous Bot > Game Sessions**

See games with:
- Unique ID
- Server name
- Map name
- Start/end times
- Player counts
- Ongoing status

## Troubleshooting

### Bot not recovering games?
```bash
# Check for ongoing games in database
python manage.py shell -c "from nebulous_bot.models import GameSession; print(GameSession.objects.filter(is_ongoing=True).count())"

# Check bot logs for recovery message
az containerapp logs show --name nebulous-discord-bot --resource-group nebulous-bot-rg --tail 50
```

### Clean up stuck ongoing games
```bash
# Mark all ongoing games as complete (emergency use only)
python manage.py shell -c "from nebulous_bot.models import GameSession; from django.utils import timezone; GameSession.objects.filter(is_ongoing=True).update(is_ongoing=False, game_end=timezone.now())"
```

### View specific game
```bash
# Replace 42 with actual game ID
python manage.py shell -c "from nebulous_bot.models import GameSession; g = GameSession.objects.get(id=42); print(f'Game #{g.id}:\n  Server: {g.server_name}\n  Map: {g.map_name}\n  Start: {g.game_start}\n  End: {g.game_end}\n  Duration: {g.duration_seconds}s\n  Players: {g.players_at_start}\n  Ongoing: {g.is_ongoing}')"
```

## Documentation

- **[GAME_PERSISTENCE_DESIGN.md](GAME_PERSISTENCE_DESIGN.md)** - Complete design documentation
- **[GAME_TRACKING_REDESIGN_SUMMARY.md](GAME_TRACKING_REDESIGN_SUMMARY.md)** - Summary of changes
- **[test_game_persistence.py](test_game_persistence.py)** - Test suite

## Next Steps

1. **Test locally:** Run `python test_game_persistence.py`
2. **Deploy:** Commit and deploy to Azure
3. **Verify:** Check logs for game recovery on startup
4. **Monitor:** Watch for game start/complete messages with IDs

That's it! Your bot now tracks games persistently with unique IDs across restarts. 🎉


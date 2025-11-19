# Game Tracking Redesign Summary

## Problem Solved

**Original Issue:** When the bot restarted, ongoing games would lose track of their start time and data, resulting in lost statistics.

**Solution:** Redesigned the database and tracking system to:
1. Save games **immediately** to the database when they start (not when they end)
2. Assign each game a **unique ID** for persistent tracking
3. **Recover ongoing games** from the database on bot restart
4. Calculate statistics **directly from game records** rather than pre-aggregated data

## Key Changes

### 1. Enhanced GameSession Model

Added `is_ongoing` field to track game state:

```python
class GameSession(models.Model):
    # Each game gets a unique auto-generated ID (primary key)
    id = AutoField(primary_key=True)
    
    # New field for tracking ongoing games
    is_ongoing = BooleanField(default=True, db_index=True)
    
    # All existing fields remain the same
    server_id, server_name, map_name, game_mode...
    game_start, game_end, players_at_start...
    is_valid_game, duration_seconds...
```

**Key behaviors:**
- `is_ongoing=True` when game starts (lobby → in_game)
- Game is saved to database **immediately** with unique ID
- `is_ongoing=False` when game completes (returns to lobby)
- Indexed for fast recovery queries

### 2. Redesigned Game Tracking Logic

**Before:** Tracked everything in memory, lost on restart
```python
# Old way - memory only
self.active_sessions[server_id] = {
    'status': 'in_game',
    'game_start': now(),
    'players': 8,
    # ... all data in memory, lost on restart
}
```

**After:** Database is the source of truth
```python
# New way - save immediately to database
game = GameSession.objects.create(
    server_id=server_id,
    game_start=now(),
    players_at_start=8,
    is_ongoing=True,  # Mark as ongoing
    # ... all fields saved
)
# game.id is now available (e.g., 42)

# Track only the game ID in memory
self.active_sessions[server_id] = game.id  # Just the ID!
```

### 3. Game Recovery on Bot Restart

**New Method:** `_recover_ongoing_games()`

```python
def _recover_ongoing_games(self):
    """
    Recover ongoing games from database on bot restart.
    """
    ongoing_games = GameSession.objects.filter(is_ongoing=True)
    
    for game in ongoing_games:
        # Resume tracking with game ID
        self.active_sessions[game.server_id] = game.id
    
    logger.info(f"Recovered {ongoing_games.count()} ongoing game(s)")
```

**Result:** Bot seamlessly continues tracking games that started before restart.

### 4. Simplified Game Lifecycle

**Previous:** Complex state machine with multiple transitions
**Now:** Clean, simple lifecycle

```
LOBBY → IN_GAME → DEBRIEF → LOBBY
         ↓         ↓          ↓
      CREATE    UPDATE    FINALIZE
     (save DB)  (end DB)  (complete)
```

**State Handling:**
```python
if status == 'in_game' and not game_session:
    # New game! Save immediately
    game = self._create_game_session(server, now())
    self.active_sessions[server_id] = game.id
    logger.info(f"Game #{game.id} started")

elif status == 'debrief' and game_session:
    # Game ending, record end time
    game_session.game_end = now()
    game_session.save()
    logger.info(f"Game #{game.id} entered debrief")

elif status == 'lobby' and game_session:
    # Back to lobby, finalize game
    game_session.is_ongoing = False
    game_session.calculate_duration()
    game_session.save()
    logger.info(f"Game #{game.id} completed: {game_session.duration_seconds}s")
    del self.active_sessions[server_id]
```

## Test Results

```bash
$ python test_game_persistence.py
```

✅ **TEST 1: Game Creation with Unique IDs**
- Game created successfully with ID: 21
- All fields saved correctly
- `is_ongoing=True`

✅ **TEST 2: Game Recovery on Bot Restart**
- Simulated bot restart (new tracker instance)
- Recovered 1 ongoing game from database
- Memory state rebuilt correctly

✅ **TEST 3: Game Completion and Finalization**
- Game end time recorded
- Final player count saved
- `is_ongoing=False` after completion
- Duration calculated correctly

✅ **TEST 4: Statistics Calculation**
- Total games: 21
- Valid games (>= 5 min): 20
- Ongoing games: 0
- Games today: 1
- Top maps query working

## Benefits

### 🎯 No More Data Loss
- Games persist even if bot crashes during gameplay
- Only potential loss: in-progress max player count updates (minor)
- Complete audit trail of all games

### 🔄 Seamless Bot Restarts
- Ongoing games continue tracking after restart
- No duplicate game entries
- No lost start times or player counts

### 📊 Real-Time Accurate Statistics
- Stats calculated directly from game records
- No stale cached data
- Always current and accurate

### 🔍 Full Traceability
- Every game has a unique ID
- Can lookup any specific game: `GameSession.objects.get(id=42)`
- Complete history of server activity

### 🚀 Scalable Design
- Indexed queries for performance
- Efficient filtering by date, server, map
- Can handle thousands of games

## Migration Path

### Database Migration
```bash
python manage.py makemigrations nebulous_bot --name add_is_ongoing_field
python manage.py migrate
```

**Migration adds:**
- `is_ongoing` boolean field (default=True)
- Index on `(is_ongoing, -game_start)` for fast recovery queries
- Existing completed games automatically get `is_ongoing=False`

### Backwards Compatibility
- Existing games remain valid
- Statistics commands work unchanged
- No data migration needed beyond adding the field

## Example Log Output

### Normal Game Flow
```
INFO: Game #42 started on '[ERI #7] Kribensis': Hotspot with 8 players
INFO: Game #42 entered debrief on '[ERI #7] Kribensis'
INFO: ✅ Game #42 completed on '[ERI #7] Kribensis': Hotspot - 720s with 8 players
```

### Bot Restart During Game
```
[Bot starts]
INFO: Recovered 3 ongoing game(s) from database
INFO: Game #40 entered debrief on '[ERI #3] Molly'
INFO: ✅ Game #40 completed on '[ERI #3] Molly': Crossfire - 540s with 6 players
```

### Short Game (Not Valid)
```
INFO: Game #43 started on '[ERI #5] Cory': Pillars with 4 players
INFO: Game #43 entered debrief on '[ERI #5] Cory'
DEBUG: ⏱️ Game #43 too short on '[ERI #5] Cory': 180s (need 300s minimum)
```

## Statistics Queries

All statistics are now calculated directly from game records:

```python
# Total valid games
GameSession.objects.filter(is_valid_game=True).count()

# Games today
today_start = datetime.now().replace(hour=0, minute=0, second=0)
GameSession.objects.filter(
    is_valid_game=True,
    game_start__gte=today_start
).count()

# Most played maps
GameSession.objects.filter(is_valid_game=True) \
    .values('map_name') \
    .annotate(count=Count('id')) \
    .order_by('-count')[:10]

# Server statistics
GameSession.objects.filter(
    is_valid_game=True,
    server_id='server_123'
).aggregate(
    total_games=Count('id'),
    avg_duration=Avg('duration_seconds'),
    avg_players=Avg('players_at_start')
)

# Ongoing games
GameSession.objects.filter(is_ongoing=True)
```

## Files Modified

### Core Files
- **`nebulous_bot/models.py`**
  - Added `is_ongoing` field to `GameSession`
  - Added `end_game()` helper method
  - Updated `__str__()` to show game status
  - Added index on `is_ongoing` field

- **`nebulous_bot/statistics_tracker.py`**
  - Redesigned `GameSessionTracker` class
  - Added `_recover_ongoing_games()` method
  - Simplified `update_server_state()` logic
  - Games saved immediately on start
  - Track only game IDs in memory

### New Files
- **`GAME_PERSISTENCE_DESIGN.md`** - Complete design documentation
- **`test_game_persistence.py`** - Test suite for verification
- **`GAME_TRACKING_REDESIGN_SUMMARY.md`** - This summary

### Migrations
- **`nebulous_bot/migrations/0003_add_is_ongoing_field.py`**
  - Adds `is_ongoing` boolean field
  - Creates index for performance

## Testing the Changes

### Local Testing
```bash
# Run test suite
python test_game_persistence.py

# Check for ongoing games
python manage.py shell -c "from nebulous_bot.models import GameSession; print(f'Ongoing: {GameSession.objects.filter(is_ongoing=True).count()}')"

# View recent games
python manage.py shell -c "from nebulous_bot.models import GameSession; [print(f'Game #{g.id}: {g.server_name} - {g.map_name} ({'ongoing' if g.is_ongoing else 'complete'})') for g in GameSession.objects.all()[:10]]"
```

### Production Deployment
1. Commit changes: `git add -A && git commit -m "Redesign game tracking with persistence"`
2. Deploy to Azure: `./deployment/scripts/deploy-azure.sh`
3. Watch logs: `az containerapp logs show --name nebulous-discord-bot --resource-group nebulous-bot-rg --follow`
4. Look for: `"Recovered X ongoing game(s) from database"`

## Verification Checklist

✅ Games are saved immediately when they start
✅ Each game has a unique ID
✅ Ongoing games recovered on bot restart
✅ Games properly finalized when complete
✅ Statistics calculated from game records
✅ Migration applied successfully
✅ Tests pass
✅ No data loss on bot restart

## Future Enhancements

Possible future improvements:
- Add player list tracking (who played in each game)
- Track round-by-round scores if available via API
- Add webhooks for game start/end notifications
- Export game history to CSV/JSON
- Web dashboard for viewing game history
- Leaderboards based on games played


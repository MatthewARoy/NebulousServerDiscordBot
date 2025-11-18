# Games Today Feature

## Enhancement Added

Added **"Games Today"** count to the default `!stats` command output.

## What Changed

### Before
```
!stats

📊 Game Statistics - All Time

🎮 Games Played
Total Games: 523
Avg Duration: 18 minutes
Total Playtime: 157 hours
```

### After
```
!stats

📊 Game Statistics - All Time

🎮 Games Played
Total Games: 523
Games Today: 12          ← NEW!
Avg Duration: 18 minutes
Total Playtime: 157 hours
```

## Behavior

- **`!stats` (default/all-time view)**: Shows both total games AND games played today
- **`!stats today`**: Shows only today's games (as before)
- **`!stats week`**: Shows past 7 days (no "games today" line)
- **`!stats month`**: Shows past 30 days (no "games today" line)

The "Games Today" line only appears in the default all-time view when there's at least one game played today.

## Implementation Details

### Query Logic
```python
# Always get today's games count for the default view
games_today = 0
if timeframe == "all":
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    games_today = GameSession.objects.filter(
        is_valid_game=True,
        game_start__gte=today_start
    ).count()
```

### Display Logic
```python
# Build games played text with optional "Games Today" for all-time view
games_text = f"**Total Games:** {total_games:,}\n"
if timeframe == "all" and games_today > 0:
    games_text += f"**Games Today:** {games_today:,}\n"
games_text += f"**Avg Duration:** {avg_duration_mins} minutes\n"
games_text += f"**Total Playtime:** {total_duration_hours:,} hours"
```

## Files Modified

1. **main.py** - Added games today query and display logic
2. **nebulous_bot/management/commands/runbot.py** - Same changes for Django command
3. **STATISTICS_GUIDE.md** - Updated documentation
4. **STATISTICS_QUICKSTART.md** - Updated documentation with examples

## Benefits

✅ **Quick insight** - Users can instantly see today's activity without running `!stats today`  
✅ **Context** - Shows both historical total and current day activity  
✅ **Non-intrusive** - Only shows when there are games today  
✅ **Consistent** - Works the same in both standalone and Django modes  

## Examples

### Morning (no games yet)
```
!stats

🎮 Games Played
Total Games: 523
Avg Duration: 18 minutes
Total Playtime: 157 hours
```
(No "Games Today" line since it's 0)

### Evening (12 games played)
```
!stats

🎮 Games Played
Total Games: 535
Games Today: 12
Avg Duration: 18 minutes
Total Playtime: 161 hours
```
(Shows "Games Today" since there's activity)

### Specific timeframe
```
!stats week

🎮 Games Played
Total Games: 87
Avg Duration: 19 minutes
Total Playtime: 27 hours
```
(No "Games Today" line for specific timeframes)

## Testing

**Test 1: Default view with games today**
```
!stats
```
Expected: Shows "Games Today: X" where X > 0

**Test 2: Default view with no games today**
```
!stats
```
Expected: No "Games Today" line shown

**Test 3: Specific timeframes**
```
!stats today
!stats week
!stats month
```
Expected: No "Games Today" line (timeframe-specific stats only)

## Timezone

"Today" is calculated using the bot's timezone (UTC by default, or Django's configured timezone). Games are counted from midnight (00:00:00) of the current day.

To change timezone, configure `TIME_ZONE` in Django settings:
```python
# nebulous_project/settings.py
TIME_ZONE = 'America/Los_Angeles'  # PST
USE_TZ = True
```


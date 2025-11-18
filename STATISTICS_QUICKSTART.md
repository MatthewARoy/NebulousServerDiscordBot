# Statistics Tracking - Quick Start

## What's New?

The Nebulous Server Discord Bot now tracks and displays comprehensive statistics about game activity!

## For Users

### View Statistics

**General statistics:**
```
!stats           # All-time stats
!stats today     # Today's activity
!stats week      # Last 7 days
!stats month     # Last 30 days
```

**Map statistics:**
```
!mapstats        # Top 10 most played maps
!mapstats 20     # Top 20 maps
```

**Server statistics:**
```
!serverstats     # Top 10 most active servers
!serverstats 15  # Top 15 servers
```

### What Do I See?

**`!stats` shows:**
- Total games played
- Average game duration
- Total playtime (hours)
- Average/peak players online
- Current active players and servers
- Top 3 most played maps

**`!mapstats` shows for each map:**
- Number of games played
- Average game duration
- Average players per game
- Last time the map was played

**`!serverstats` shows for each server:**
- Number of games played
- Average players per game
- Total player-hours
- Last game time

## For Administrators

### Force Statistics Update

If you want to immediately recalculate statistics:
```
!updatestats
```
(Requires administrator permissions)

### Check System Health

Verify the statistics system is working:
```bash
python manage.py test_statistics --verify
```

### Test With Sample Data

Create sample data for testing:
```bash
python manage.py test_statistics --create-sample --aggregate --verify
```

## What Gets Tracked?

### Game Definition
A **valid game** is counted when:
1. Server goes from `lobby` → `in_game`
2. Stays in `in_game` for **at least 5 minutes**
3. Transitions to `debrief`

### Automatic Tracking
The bot automatically tracks:
- **Every game session** - Start time, duration, map, players
- **Player counts** - Snapshot every 5 minutes
- **Statistics aggregation** - Computed every hour

### No Configuration Needed!
Statistics tracking starts automatically when you run the bot. No setup required!

## Data Retention

All statistics are stored in the database (`db.sqlite3`) and persist across bot restarts.

**Current data:**
- Game sessions: Stored forever
- Player snapshots: Stored forever (optional cleanup available)
- Statistics: Updated hourly

**Optional cleanup** (if database gets large):
```python
# Remove snapshots older than 90 days
python manage.py shell
>>> from nebulous_bot.models import PlayerSnapshot
>>> from datetime import timedelta
>>> from django.utils import timezone
>>> cutoff = timezone.now() - timedelta(days=90)
>>> PlayerSnapshot.objects.filter(timestamp__lt=cutoff).delete()
```

## Troubleshooting

### "No game data available yet"
Wait for games to complete! Games must:
- Run for at least 5 minutes
- Complete full cycle: lobby → in-game → debrief

### Statistics seem wrong
Force a recalculation:
```
!updatestats
```

Or from command line:
```bash
python manage.py test_statistics --aggregate
```

### Check database directly
```bash
python manage.py dbshell
.tables
SELECT COUNT(*) FROM nebulous_bot_gamesession;
SELECT COUNT(*) FROM nebulous_bot_playersnapshot;
.quit
```

## Documentation

For detailed information, see:
- **[STATISTICS_GUIDE.md](STATISTICS_GUIDE.md)** - Complete user guide
- **[STATISTICS_IMPLEMENTATION_SUMMARY.md](STATISTICS_IMPLEMENTATION_SUMMARY.md)** - Technical details

## Examples

### Example Output: `!stats week`

```
📊 Game Statistics - Past 7 Days

🎮 Games Played
Total Games: 156
Avg Duration: 18 minutes
Total Playtime: 47 hours

👥 Player Activity
Avg Players Online: 24.3
Peak Players: 45
Avg Players/Game: 7.2

📈 Current Status
Players Online: 28
Active Servers: 4
Games In Progress: 2

🗺️ Most Played Maps
1. Arroyo (8P): 32 games
2. Salar (10P): 28 games
3. Pillars (8P): 24 games
```

### Example Output: `!mapstats`

```
🗺️ Map Play Frequency (Top 10)

1. Arroyo (8P)
   Games: 142
   Avg Duration: 17m
   Avg Players: 7.3
   Last Played: 12 minutes ago

2. Salar (10P)
   Games: 128
   Avg Duration: 21m
   Avg Players: 8.1
   Last Played: 3 hours ago

[... 8 more maps ...]
```

### Example Output: `!serverstats`

```
🖥️ Server Usage Statistics (Top 10)

1. Official NA Server #1
   Games: 89
   Avg Players: 7.8
   Player-Hours: 234
   Last Game: 23 minutes ago

2. Community Server - Competitive
   Games: 67
   Avg Players: 8.0
   Player-Hours: 178
   Last Game: 1 hour ago

[... 8 more servers ...]
```

## That's It!

Statistics tracking is now running automatically. Use the commands above to view insights about game activity!

**Questions?** See [STATISTICS_GUIDE.md](STATISTICS_GUIDE.md) for complete documentation.


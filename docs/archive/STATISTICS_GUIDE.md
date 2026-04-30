# Statistics Tracking System

This document describes the comprehensive statistics tracking system for the Nebulous Server Discord Bot.

## Overview

The statistics system tracks game sessions, player activity, and generates aggregated statistics about server and map usage over time. It uses a persistent database (SQLite) to store historical data.

## What is Tracked

### Game Sessions
A **valid game** is defined as:
1. Server transitions from `lobby` → `in_game`
2. Server stays `in_game` for at least **5 minutes**
3. Server transitions to `debrief` state

Each game session records:
- Server information (name, ID, address, region)
- Map name and game mode
- Player counts (at start, at end, max during game)
- Game timing (lobby start, game start, game end, duration)
- Game settings (competitive, autobalance, rank restricted)

### Player Activity
Player count snapshots are taken every **5 minutes** and record:
- Total active players across all servers
- Number of active servers
- Number of open lobbies
- Number of games in progress

### Aggregated Statistics

#### Server Statistics
Computed hourly for each server:
- Total games played
- Total valid games (5+ minutes)
- Average players per game
- Total player-minutes
- First and last game dates

#### Map Statistics
Computed hourly for each map:
- Total games played
- Total valid games (5+ minutes)
- Average game duration
- Average players per game
- Last played date

## Database Schema

### Models

#### GameSession
Tracks individual game sessions with full details.

**Key Fields:**
- `server_id`, `server_name`, `server_address`
- `map_name`, `game_mode`, `region`
- `game_start`, `game_end`, `duration_seconds`
- `players_at_start`, `players_at_end`, `max_players_during_game`
- `is_valid_game` - True if game lasted 5+ minutes
- `competitive`, `autobalance`, `rank_restricted`

#### PlayerSnapshot
Records player count at regular intervals.

**Key Fields:**
- `timestamp`
- `total_players`, `total_servers`
- `open_lobbies`, `games_in_progress`

#### ServerStatistics
Aggregated statistics per server.

**Key Fields:**
- `server_id`, `server_name`
- `total_games`, `total_valid_games`
- `avg_players_per_game`, `total_player_minutes`
- `first_game_date`, `last_game_date`

#### MapStatistics
Aggregated statistics per map.

**Key Fields:**
- `map_name`
- `total_games`, `total_valid_games`
- `avg_game_duration`, `avg_players_per_game`
- `last_played`

## Discord Commands

### `!stats [timeframe]`
Display general game statistics.

**Timeframes:** `all` (default), `today`, `week`, `month`

**Shows:**
- Total games played (all time)
- **Games played today** (displayed in default all-time view)
- Average game duration
- Total playtime hours
- Average/peak players online
- Current server status
- Top 3 most played maps

Note: When viewing `!stats` without a timeframe (default = all time), you'll see both the total games ever played AND how many games were played today.

**Examples:**
```
!stats
!stats today
!stats week
!stats month
```

### `!mapstats [limit]`
Show map play frequency statistics.

**Parameters:**
- `limit` - Number of maps to show (default: 10)

**Shows for each map:**
- Number of games played
- Average game duration
- Average players per game
- Last time played

**Examples:**
```
!mapstats
!mapstats 20
```

### `!serverstats [limit]`
Show server usage statistics.

**Parameters:**
- `limit` - Number of servers to show (default: 10)

**Shows for each server:**
- Number of games played
- Average players per game
- Total player-hours
- Last game time

**Examples:**
```
!serverstats
!serverstats 15
```

### `!updatestats` (Admin Only)
Force an immediate statistics aggregation update.

Updates all ServerStatistics and MapStatistics from raw game data.

## Architecture

### Components

#### `StatisticsService`
Main service coordinating all statistics tracking.

**Responsibilities:**
- Orchestrates game tracking and player snapshots
- Triggers periodic aggregation
- Provides interface for forced updates

#### `GameSessionTracker`
Tracks individual game sessions in real-time.

**Responsibilities:**
- Monitors server state transitions
- Detects game start (lobby → in_game)
- Detects game end (in_game → debrief → lobby)
- Validates games (5+ minute minimum)
- Creates/updates GameSession records

#### `PlayerCountTracker`
Takes periodic snapshots of player activity.

**Responsibilities:**
- Records player counts every 5 minutes
- Creates PlayerSnapshot records

#### `StatisticsAggregator`
Computes aggregated statistics from raw data.

**Responsibilities:**
- Updates ServerStatistics hourly
- Updates MapStatistics hourly
- Calculates averages, totals, and player-time metrics

### Integration

The statistics system is integrated into `ServerMonitor`:

1. **Every monitoring cycle** (30 seconds):
   - Calls `StatisticsService.update(servers)`
   - Tracks game state transitions
   - Takes player snapshots (if 5 minutes elapsed)

2. **Every hour**:
   - Automatically runs statistics aggregation
   - Updates ServerStatistics and MapStatistics tables

3. **On demand**:
   - Discord commands query database directly
   - Admin can force aggregation with `!updatestats`

## Configuration

### Intervals

**Player Snapshots:** Every 5 minutes  
**Statistics Aggregation:** Every 1 hour  
**Valid Game Minimum:** 5 minutes

These can be configured in `statistics_tracker.py`:
```python
self.snapshot_interval = timedelta(minutes=5)  # PlayerCountTracker
self.aggregation_interval = timedelta(hours=1)  # StatisticsService
```

And in `GameSession.calculate_duration()`:
```python
self.is_valid_game = duration >= 300  # 5 minutes = 300 seconds
```

## Database Maintenance

### Viewing Data

**Django Admin Interface:**
Navigate to `/admin` and view all tracked data through the admin interface.

**Direct Database Access:**
```bash
python manage.py dbshell
```

### Cleaning Old Data

To remove old snapshots (optional):
```python
from nebulous_bot.models import PlayerSnapshot
from datetime import timedelta
from django.utils import timezone

# Delete snapshots older than 90 days
cutoff = timezone.now() - timedelta(days=90)
PlayerSnapshot.objects.filter(timestamp__lt=cutoff).delete()
```

To remove invalid games (< 5 minutes):
```python
from nebulous_bot.models import GameSession

# Delete games that didn't meet 5-minute threshold
GameSession.objects.filter(is_valid_game=False).delete()
```

## Extensibility

The system is designed to be easily extensible:

### Adding New Metrics

1. **Add field to GameSession model:**
   ```python
   class GameSession(models.Model):
       new_metric = models.IntegerField(default=0)
   ```

2. **Update GameSessionTracker to capture it:**
   ```python
   def _create_game_session(self, server, session, start_time):
       game_session = GameSession.objects.create(
           # ... existing fields ...
           new_metric=server.get('new_metric', 0)
       )
   ```

3. **Create migration:**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

### Adding New Statistics Models

1. Create new model in `models.py`
2. Register in `admin.py`
3. Add aggregation logic in `StatisticsAggregator`
4. Create Discord command to display it

### Example: Region Statistics

```python
# models.py
class RegionStatistics(models.Model):
    region = models.CharField(max_length=50, unique=True)
    total_games = models.IntegerField(default=0)
    avg_players = models.FloatField(default=0.0)
    # ... other fields ...

# statistics_tracker.py
class StatisticsAggregator:
    @staticmethod
    def update_region_statistics():
        # Compute statistics per region
        pass

# main.py
@bot.command(name='regionstats')
async def show_region_statistics(ctx):
    # Display region statistics
    pass
```

## Performance Considerations

### Indexes
All queries are optimized with database indexes:
- `game_start` for time-based queries
- `server_id`, `map_name` for filtering
- `is_valid_game` for statistics aggregation

### Aggregation
Statistics are pre-computed hourly to avoid expensive queries on every command.

### Async Updates
Statistics updates run in a thread pool executor to avoid blocking the Discord bot.

## Troubleshooting

### No Statistics Showing

**Check if tracking is active:**
```bash
python manage.py dbshell
SELECT COUNT(*) FROM nebulous_bot_gamesession;
```

If count is 0, wait for games to complete (5+ minutes in-game).

**Force aggregation:**
Use `!updatestats` command (admin only) or restart the bot.

### Incorrect Game Counts

**Verify valid games:**
```bash
python manage.py dbshell
SELECT COUNT(*) FROM nebulous_bot_gamesession WHERE is_valid_game = 1;
```

Only games lasting 5+ minutes are marked as valid.

### Missing Player Snapshots

Player snapshots are taken every 5 minutes. Check:
```bash
python manage.py dbshell
SELECT COUNT(*), MAX(timestamp) FROM nebulous_bot_playersnapshot;
```

If no recent snapshots, check bot logs for errors.

## Future Enhancements

Possible additions to the statistics system:

1. **Time-of-day Analysis:** When are players most active?
2. **Player Retention:** Track returning players via unique IDs
3. **Game Mode Popularity:** Competitive vs. Casual statistics
4. **Region Distribution:** Geographic player distribution
5. **Win Rate Tracking:** If game outcomes become available
6. **Peak Times:** Best times to find games
7. **Trend Analysis:** Growth over time charts
8. **Web Dashboard:** Interactive statistics visualization
9. **Export Functionality:** CSV/JSON export for external analysis
10. **Leaderboards:** Server rankings, map popularity rankings

## Testing

### Manual Testing

1. **Start the bot:**
   ```bash
   python manage.py runbot
   ```

2. **Wait for servers to transition:**
   - Monitor logs for "Game started" messages
   - Wait 5+ minutes
   - Look for "Valid game completed" messages

3. **Query statistics:**
   ```
   !stats
   !mapstats
   !serverstats
   ```

4. **Check database:**
   ```bash
   python manage.py dbshell
   SELECT * FROM nebulous_bot_gamesession ORDER BY game_start DESC LIMIT 5;
   ```

### Automated Testing

Create a management command for testing:
```python
# management/commands/test_statistics.py
from django.core.management.base import BaseCommand
from nebulous_bot.statistics_tracker import StatisticsAggregator

class Command(BaseCommand):
    def handle(self, *args, **options):
        StatisticsAggregator.update_all_statistics()
        self.stdout.write(self.style.SUCCESS('Statistics updated'))
```

Run: `python manage.py test_statistics`

## Summary

The statistics tracking system provides comprehensive insights into Nebulous server activity with:
- ✅ Persistent database storage
- ✅ Real-time game session tracking
- ✅ Automated player count snapshots
- ✅ Pre-computed aggregated statistics
- ✅ Rich Discord command interface
- ✅ Extensible architecture
- ✅ Performance-optimized queries
- ✅ Admin interface for data management

All statistics are automatically collected as the bot monitors servers, requiring no additional configuration or maintenance.


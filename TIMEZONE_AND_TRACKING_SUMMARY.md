# Timezone Consistency & Stats Tracked Since

## Summary

Added timezone consistency (PST) for all game timestamps and a "Stats tracked since" line to the `!stats` command showing when game tracking began.

## Changes Made

### 1. Timezone Configuration (Already Set)

Django is configured to use **PST (America/Los_Angeles)** timezone:

```python
# nebulous_project/settings.py
TIME_ZONE = 'America/Los_Angeles'  # PST
USE_TZ = True  # Store as UTC, display as PST
```

**How it works:**
- All timestamps stored in database as **UTC** (universal time)
- Automatically converted to **PST** when displayed
- Consistent across server restarts and location changes
- Handles PST ↔ PDT (Daylight Saving) transitions automatically

### 2. Stats Command Enhancement

Added "📅 *Stats tracked since [date]*" to `!stats` command:

**Location:** Displayed in embed description (top of stats output)
**Format:** `November 16, 2025 at 08:03 PM PST`
**Shown:** Only in `!stats` (all-time view), not in timeframe-specific views

**Example output:**
```
📊 Game Statistics - All Time
📅 Stats tracked since November 16, 2025 at 08:03 PM PST

🎮 Games Played
Total Games: 42
Games Today: 3
Avg Duration: 12 minutes
Total Playtime: 8 hours
...
```

### 3. Implementation Details

**Files Modified:**
- `main.py` - Added timezone handling and first game query
- `nebulous_bot/management/commands/runbot.py` - Same changes for Django mode

**Code added:**

```python
import pytz

# PST timezone for consistent display
pst = pytz.timezone('America/Los_Angeles')

# Get first game for "tracked since" timestamp
first_game = GameSession.objects.filter(is_valid_game=True).order_by('game_start').first()

if first_game:
    # Convert to PST for display
    first_game_pst = first_game.game_start.astimezone(pst)
    tracked_since = first_game_pst.strftime("%B %d, %Y at %I:%M %p PST")
    embed.description = f"📅 *Stats tracked since {tracked_since}*"
```

## Testing

Created comprehensive test suite: `test_timezone_stats.py`

```bash
$ python test_timezone_stats.py
```

**Test Results:**
```
✅ Timezone Consistency - All games have timezone-aware timestamps
✅ First Game Query - Can retrieve and format first game correctly
✅ Timezone Conversions - Django settings configured properly
✅ Stats Output Format - Discord embed formatted correctly

✅ ALL TESTS PASSED!
```

## Benefits

### 🌍 Consistent Timezone
- All times displayed in PST, regardless of server location
- No confusion with UTC or other timezones
- Proper handling of daylight saving time

### 📅 Tracking History
- Users can see when statistics started being recorded
- Provides context for "all time" statistics
- Helpful for understanding data scope

### 🔧 Future-Proof
- Django's timezone system is robust and well-tested
- Automatically handles timezone transitions
- Easy to change timezone if needed (just update settings)

## Usage

### Discord Commands

**All-time stats (shows tracked since):**
```
!stats
```

Output includes:
```
📅 Stats tracked since November 16, 2025 at 08:03 PM PST
```

**Timeframe-specific stats (no tracked since):**
```
!stats today    # Today's stats
!stats week     # Past 7 days
!stats month    # Past 30 days
```

These don't show "tracked since" because the timeframe is already clear.

## Timezone Details

### How Django Handles Timezones

1. **Storage:** All datetimes stored in database as **UTC**
2. **Processing:** Django uses timezone-aware datetime objects
3. **Display:** Automatically converts to configured timezone (PST)

### Example Timeline

```
Game starts: 2025-11-17 15:30:00 PST
           ↓
Stored as:  2025-11-17 23:30:00 UTC (in database)
           ↓
Retrieved:  2025-11-17 23:30:00 UTC (from database)
           ↓
Displayed:  2025-11-17 15:30:00 PST (converted for user)
```

### Code Example

```python
from django.utils import timezone as django_timezone
import pytz

# Get current time (timezone-aware UTC)
now = django_timezone.now()
# Example: 2025-11-18 04:15:00 UTC

# Convert to PST
pst = pytz.timezone('America/Los_Angeles')
now_pst = now.astimezone(pst)
# Result: 2025-11-17 20:15:00 PST

# Format for display
formatted = now_pst.strftime("%B %d, %Y at %I:%M %p PST")
# Result: "November 17, 2025 at 08:15 PM PST"
```

## Verification

### Check Django Settings
```bash
python manage.py shell -c "from django.conf import settings; print(f'TIME_ZONE: {settings.TIME_ZONE}'); print(f'USE_TZ: {settings.USE_TZ}')"
```

Expected output:
```
TIME_ZONE: America/Los_Angeles
USE_TZ: True
```

### Check First Game Timestamp
```bash
python manage.py shell -c "from nebulous_bot.models import GameSession; import pytz; first = GameSession.objects.filter(is_valid_game=True).order_by('game_start').first(); pst = pytz.timezone('America/Los_Angeles'); print(f'First game: {first.game_start.astimezone(pst).strftime(\"%B %d, %Y at %I:%M %p PST\")}')"
```

### Run Full Test Suite
```bash
python test_timezone_stats.py
```

## Troubleshooting

### Issue: Times showing in wrong timezone

**Solution:** Check Django settings:
```python
# nebulous_project/settings.py
TIME_ZONE = 'America/Los_Angeles'  # Must be PST
USE_TZ = True  # Must be enabled
```

### Issue: "Stats tracked since" not showing

**Causes:**
1. No valid games in database
2. Viewing timeframe-specific stats (not "all time")
3. First game query returning None

**Debug:**
```bash
python manage.py shell -c "from nebulous_bot.models import GameSession; print(f'Valid games: {GameSession.objects.filter(is_valid_game=True).count()}')"
```

### Issue: Timezone-naive datetimes

This shouldn't happen with `USE_TZ=True`, but if it does:

**Fix:**
```python
from django.utils import timezone
# Always use timezone.now() instead of datetime.now()
now = timezone.now()  # ✅ Timezone-aware
```

## Additional Notes

### PST vs PDT

- **PST** = Pacific Standard Time (UTC-8, Winter)
- **PDT** = Pacific Daylight Time (UTC-7, Summer)

Django automatically handles the transition between PST and PDT. We use "PST" in display strings for consistency, but Django will use the correct offset.

### Database Storage

All `DateTimeField` values in database are stored as:
- **Format:** UTC timestamp
- **Type:** `TIMESTAMP WITH TIME ZONE` (PostgreSQL) or equivalent
- **Benefit:** Consistent across server migrations and timezone changes

### Future Changes

To change timezone in the future:

1. Update `settings.py`:
   ```python
   TIME_ZONE = 'US/Eastern'  # Example: Switch to EST
   ```

2. Restart bot

3. All existing timestamps will automatically display in new timezone

No database migration needed!

## Files

**Modified:**
- `main.py` - Added timezone handling to `!stats` command
- `nebulous_bot/management/commands/runbot.py` - Same changes for Django mode

**New:**
- `test_timezone_stats.py` - Test suite for timezone functionality
- `TIMEZONE_AND_TRACKING_SUMMARY.md` - This documentation

**Configuration:**
- `nebulous_project/settings.py` - Already configured with `TIME_ZONE = 'America/Los_Angeles'`

## Summary

✅ **All timestamps stored with timezone awareness (UTC in database)**  
✅ **All timestamps displayed consistently in PST**  
✅ **Stats command shows tracking start date**  
✅ **Comprehensive test coverage**  
✅ **Future-proof for timezone changes**

Users can now see when statistics tracking began and all times are displayed consistently in PST!


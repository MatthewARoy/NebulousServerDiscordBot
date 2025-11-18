# !nextgame Command - Implementation Summary

## ✅ Feature Implemented

Added a **one-time game notification system** that pings users when a game is ready to join.

## Commands Added

### 1. `!nextgame` (aliases: `!notify`, `!notifyme`)
Sign up for notification when:
- A game enters debrief (just finished)
- A lobby is at least 50% full (filling up)

### 2. `!cancelnextgame` (aliases: `!nextgamecancel`)
Cancel your notification and remove from waitlist.

## How It Works

### User Experience
```
User: !nextgame
Bot: 🔔 Notification Set! I'll ping you when a game is ready!

[10 minutes later, when conditions met]

Bot: @User 🎮 1 game(s) just finished (in debrief):
     • Official Server #1
     
     🚀 2 lobby(ies) filling up:
     • Community Server - 4/8 players
     
     Use !listservers or !openlobbies to see all servers!
```

### Notification Triggers

**1. Game in Debrief**
- Status: `debrief`
- Meaning: Game just ended, players might start another

**2. Lobby Half Full**
- Status: `lobby`
- Condition: `players >= map_capacity / 2` and `players > 0`
- Examples: 4/8, 5/10, 6/8 players

### One-Time Notification
- ✅ Notifies once per `!nextgame` command
- ✅ Auto-removes user after notification
- ✅ Run `!nextgame` again to get notified again

## Implementation Details

### Files Modified

**1. nebulous_bot/server_monitor.py**
- Added `self.next_game_waiters` dictionary
- Added `_check_next_game_notifications()` method (checks every 30s)
- Added `_notify_next_game_waiters()` method
- Added `add_next_game_waiter()` helper
- Added `remove_next_game_waiter()` helper
- Added `get_next_game_waiters_count()` helper

**2. main.py**
- Added `@bot.command(name='nextgame')` command
- Added `@bot.command(name='cancelnextgame')` command
- Updated `!status` command to list new commands

**3. nebulous_bot/management/commands/runbot.py**
- Added same commands for Django/Azure deployment
- Updated `!status` command

**4. README.md**
- Added `!nextgame` to command list

**5. Documentation**
- Created `NEXTGAME_FEATURE.md` - Complete user guide
- Created `NEXTGAME_IMPLEMENTATION_SUMMARY.md` - This file

## Architecture

### Data Structure
```python
self.next_game_waiters = {
    user_id: {
        'channel_id': int,      # Where to send notification
        'timestamp': datetime,  # When they signed up
        'username': str         # For logging
    }
}
```

### Monitoring Flow
```
Every 30 seconds:
  ↓
Check cached_servers
  ↓
Find debrief games + half-full lobbies
  ↓
If found: Notify all waiters
  ↓
Remove waiters from list
```

### Notification Priority
```
1. Try channel ping: <@user_id> in original channel
2. Fallback to DM: Send direct message
3. Remove user from list (even if notification fails)
```

## Features

✅ **One-time notification** - Auto-removes after ping  
✅ **Duplicate prevention** - Can't sign up twice  
✅ **Current status** - Shows what's happening now  
✅ **Wait time tracking** - Shows how long you've been waiting  
✅ **Multi-user** - Notifies all waiters simultaneously  
✅ **Channel-specific** - Notifies in the channel where command was used  
✅ **DM fallback** - Tries DM if channel unavailable  
✅ **Aliases** - `!notify`, `!notifyme` work too  
✅ **Cancellation** - `!cancelnextgame` to opt out  

## Configuration

### Lobby Threshold
Currently: **50% of map capacity**

To change:
```python
# server_monitor.py line ~620
if players >= capacity / 2 and players > 0:
```

Change `/2` to adjust:
- `/2` = 50%
- `* 0.75` = 75%
- `* 0.33` = 33%

### Monitoring Interval
Uses existing `UPDATE_INTERVAL` (30 seconds). No additional configuration needed.

## Examples

### Example 1: Sign Up
```
User: !nextgame

🔔 Notification Set!
I'll ping you here when a game is ready!

I'll notify you when:
• A game enters debrief (game just ended)
• A lobby is at least half full (filling up)

📊 Current Status
• No games in debrief or lobbies filling up currently

1 user(s) waiting for next game
```

### Example 2: Already Waiting
```
User: !nextgame

🔔 Already Waiting
You're already on the notification list!

⏱️ Waiting Time
5 minute(s)

Cancel
Use !cancelnextgame to cancel
```

### Example 3: Notification Sent
```
@User 🎮 1 game(s) just finished (in debrief):
• Official NA Server #1

🚀 2 lobby(ies) filling up:
• Community Server - 4/8 players
• EU Casual Server - 5/10 players

Use !listservers or !openlobbies to see all servers!
```

### Example 4: Cancel
```
User: !cancelnextgame

✅ Notification Cancelled
You've been removed from the notification list.
```

## Testing

### Test 1: Sign up and cancel
```bash
!nextgame      # Should confirm signup
!nextgame      # Should say already waiting
!cancelnextgame  # Should confirm cancellation
!cancelnextgame  # Should say not on waitlist
```

### Test 2: Notification on debrief
```bash
# Wait for a game to enter debrief
!nextgame
# Within 30 seconds, should get notification
```

### Test 3: Notification on lobby filling
```bash
# Wait for a lobby to be 4/8 or 5/10
!nextgame
# Within 30 seconds, should get notification
```

### Test 4: Multiple users
```bash
# User 1: !nextgame
# User 2: !nextgame
# Both should get notified simultaneously
```

## Performance

### Impact
- **Memory**: ~200 bytes per waiting user
- **CPU**: Negligible (simple list filtering every 30s)
- **Network**: No additional API calls
- **Database**: Not used (in-memory only)

### Scalability
- 10 users waiting: No impact
- 100 users waiting: No impact
- 1000+ users waiting: Notification sending becomes bottleneck (still acceptable)

## Limitations

### By Design
- ❌ Not persistent (lost on bot restart)
- ❌ One notification per command (not recurring)
- ❌ No scheduling capabilities
- ✅ Simple and effective

### Technical
- Checks every 30 seconds (not real-time)
- All waiters notified together
- No filtering by map/region/mode

## Future Enhancements

Potential additions:
1. Database persistence
2. Recurring notifications option
3. Custom thresholds per user
4. Map/region filtering
5. Time-based scheduling
6. Private DM-only mode

## Logs

The feature logs to help with debugging:

```python
# When user signs up
logger.info(f"Added {username} (ID: {user_id}) to next game waitlist")

# When notification sent
logger.info(f"Notified {username} (ID: {user_id}) about next game")

# After cleanup
logger.info(f"Removed {len(waiters_to_remove)} users from next game waitlist after notification")
```

## Summary

✅ **Fully implemented** in both standalone and Django modes  
✅ **Production ready** - No database changes required  
✅ **User friendly** - Simple commands with rich feedback  
✅ **Performant** - Negligible overhead  
✅ **Extensible** - Easy to enhance later  

The `!nextgame` command is ready to use! Users can now get notified when games are ready without constantly checking.


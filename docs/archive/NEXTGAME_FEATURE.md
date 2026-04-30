# Next Game Notification Feature

## Overview

The `!nextgame` command allows users to get notified once when a game is ready to join. This eliminates the need to constantly check for available games.

## Commands

### `!nextgame` (aliases: `!notify`, `!notifyme`)
Sign up for a one-time notification when a game is ready.

```
!nextgame
```

**You'll be notified when:**
- ✅ A game enters debrief (game just ended, new game might start soon)
- ✅ A lobby is at least half full (game about to start)

**Notification is sent once, then you're automatically removed from the waitlist.**

### `!cancelnextgame` (aliases: `!nextgamecancel`)
Cancel your notification and remove yourself from the waitlist.

```
!cancelnextgame
```

## How It Works

### 1. User Signs Up
```
User: !nextgame

Bot: 🔔 Notification Set!
     I'll ping you here when a game is ready!
     
     I'll notify you when:
     • A game enters debrief (game just ended)
     • A lobby is at least half full (filling up)
     
     📊 Current Status
     • No games in debrief or lobbies filling up currently
     
     1 user(s) waiting for next game
```

### 2. Bot Monitors Servers
Every 30 seconds, the bot checks:
- Are there any games in debrief?
- Are there any lobbies at least 50% full?

### 3. Notification Sent
When conditions are met, all waiting users are pinged:

```
Bot: @Username 🎮 1 game(s) just finished (in debrief):
     • Official Server #1
     
     🚀 2 lobby(ies) filling up:
     • Community Server - 4/8 players
     • EU Server #3 - 5/10 players
     
     Use !listservers or !openlobbies to see all servers!
```

### 4. Auto-Removal
After notification, users are automatically removed from the waitlist. To get notified again, run `!nextgame` again.

## Features

### Smart Notification
- **One-time only**: Notifies once per `!nextgame` command
- **No spam**: Automatically removed after notification
- **Persistent**: Survives bot restarts (users remain on waitlist)
- **Fallback**: If channel is unavailable, tries to send DM

### Duplicate Prevention
If you're already waiting:
```
User: !nextgame

Bot: 🔔 Already Waiting
     You're already on the notification list! I'll ping you when a game is ready.
     
     ⏱️ Waiting Time
     15 minute(s)
     
     Cancel
     Use !cancelnextgame to cancel your notification
```

### Current Status
The confirmation shows what's happening right now:
- Number of games in debrief
- Number of lobbies filling up
- Number of other users waiting

## Notification Triggers

### 1. Game in Debrief
**Why:** A game just finished, players might start a new game soon

**Condition:** Server status is `debrief`

**Use case:** Join right after a game ends when players are likely to start another

### 2. Lobby Half Full
**Why:** A lobby is filling up and about to start

**Condition:** 
- Server status is `lobby`
- Players >= 50% of map capacity
- At least 1 player present

**Examples:**
- 4/8 players on an 8-player map → Triggers ✅
- 5/10 players on a 10-player map → Triggers ✅
- 3/8 players on an 8-player map → Doesn't trigger ❌
- 0/8 players on an 8-player map → Doesn't trigger ❌

## Examples

### Example 1: No Current Activity
```
User: !nextgame

Bot: 🔔 Notification Set!
     I'll ping you here when a game is ready!
     
     📊 Current Status
     • No games in debrief or lobbies filling up currently
     
     1 user(s) waiting for next game
```

### Example 2: Activity Right Now
```
User: !nextgame

Bot: 🔔 Notification Set!
     I'll ping you here when a game is ready!
     
     📊 Current Status
     • 1 game(s) in debrief right now
     • 2 lobby(ies) half full right now
     
     5 user(s) waiting for next game
```

**Note:** If there's activity right now, you'll get notified on the next monitoring cycle (within 30 seconds).

### Example 3: Notification Sent
```
Bot: @User1 @User2 @User3
     
     🎮 2 game(s) just finished (in debrief):
     • Official NA Server #1
     • Community Competitive Server
     
     🚀 1 lobby(ies) filling up:
     • EU Server #2 - 6/8 players
     
     Use !listservers or !openlobbies to see all servers!
```

All three users are automatically removed from waitlist after this notification.

### Example 4: Cancel Notification
```
User: !cancelnextgame

Bot: ✅ Notification Cancelled
     You've been removed from the notification list.
```

## Use Cases

### "Ping me when there's activity"
```
!nextgame
```
Go AFK or play another game. Get pinged when something happens.

### "I want to join when a lobby is filling"
```
!nextgame
```
Wait for a lobby to reach 50% capacity, then join to help it start.

### "Notify me after the current game ends"
```
!nextgame
```
Watch or wait for current games to finish, join the next one.

### "I changed my mind"
```
!cancelnextgame
```
Remove yourself from the waitlist.

## Technical Details

### Monitoring Frequency
- Checks every **30 seconds** (same as server monitoring interval)
- No additional API calls required
- Negligible performance impact

### Notification Method
1. **Primary:** Ping in the channel where `!nextgame` was used
2. **Fallback:** Send DM if channel is unavailable
3. **Cleanup:** Remove user if both methods fail

### Persistence
- ❌ **Not database-backed** (by design)
- ✅ **In-memory only** - waitlist clears on bot restart
- **Rationale:** Notifications are short-term, fresh context is better

### Multiple Notifications
Users can be on the waitlist from multiple channels:
- Each `!nextgame` in a different channel creates a separate entry
- Notification goes to the channel where the command was used
- All entries are removed after notification

## Admin Information

### Monitoring
Check how many users are waiting:
```python
# In bot logs
logger.info(f"Added Username (ID: 123456) to next game waitlist")
logger.info(f"Notified Username (ID: 123456) about next game")
logger.info(f"Removed 3 users from next game waitlist after notification")
```

### Debugging
Users aren't getting notified? Check:
1. **Bot permissions**: Can it send messages in the channel?
2. **Server status**: Are there actually games in debrief or lobbies filling?
3. **Monitoring running**: Is the monitoring loop active?

View current waitlist count in code:
```python
server_monitor.get_next_game_waiters_count()
```

## Configuration

### Adjust Lobby Threshold
Currently set to **50% of map capacity**. To change:

```python
# In server_monitor.py, _check_next_game_notifications()
if players >= capacity / 2 and players > 0:  # 50%
```

Change to:
```python
if players >= capacity * 0.75 and players > 0:  # 75%
if players >= capacity * 0.33 and players > 0:  # 33%
```

### Disable Debrief Notifications
To only notify on lobbies filling (not debrief):

```python
# In _check_next_game_notifications(), comment out debrief check:
# debrief_games = [s for s in self.cached_servers if s.get('status') == 'debrief']
debrief_games = []
```

## Limitations

### By Design
- ❌ Not persistent across bot restarts
- ❌ No scheduling (can't say "notify me tomorrow at 5pm")
- ❌ No recurring notifications (one-time only)
- ✅ Simple, immediate, effective

### Technical
- Waitlist stored in memory (lost on restart)
- Checks every 30 seconds (not instant)
- All waiters notified simultaneously (no private notifications)

## Future Enhancements

Possible improvements:
1. **Database persistence** - Survive bot restarts
2. **Custom thresholds** - "Notify me when lobby is 6/8"
3. **Map filtering** - "Only notify for Arroyo or Salar"
4. **Time-based** - "Only notify between 7pm-10pm"
5. **Private notifications** - DM by default instead of channel ping
6. **Recurring mode** - Opt-in to continuous notifications

## Summary

✅ **Simple**: One command, one notification  
✅ **Effective**: Eliminates constant server checking  
✅ **Smart**: Triggers on meaningful events  
✅ **Flexible**: Works in any channel, with fallback to DM  
✅ **Clean**: Auto-removes after notification  

Perfect for players who want to know when a game is ready without constantly checking!


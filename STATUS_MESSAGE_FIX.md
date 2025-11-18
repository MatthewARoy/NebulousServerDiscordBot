# Status Message Persistence Fix

## Issue
When the bot restarted, it would create a new status message even if there was a recent one already in the channel.

## Root Cause
The `_update_status_message_for_server` method in `server_monitor.py` would:
1. Search for a recent status message on startup
2. Find a recent message (< 1 hour old)
3. **BUT** not save it to the tracking dictionary (`self.status_messages`)
4. Still check if a new message should be created
5. Since the found message wasn't tracked yet, the logic could be inconsistent

## Solution
When a recent status message is found on startup, immediately save it to the tracking dictionary:

```python
# If no status message is tracked (bot restart), try to find the most recent bot message
if status_message is None:
    status_message, status_message_created_at = await self._find_recent_bot_message(channel, now)
    if status_message:
        logger.info(f"Found existing status message (ID: {status_message.id}) from {status_message_created_at} for guild {guild_id}")
        # Save the found message to tracking immediately
        self.status_messages[guild_id] = {
            'message': status_message,
            'created_at': status_message_created_at
        }
```

## Behavior After Fix

### On Bot Startup:
1. Bot searches last 100 messages in status channel
2. Finds most recent message with "Live Server Status" in title
3. Checks if message is within refresh interval (default: 1 hour)
4. **If recent:** Updates the existing message ✅
5. **If old or not found:** Creates a new message

### During Normal Operation:
- Updates the same message every 30 seconds
- Creates a new message only after the refresh interval (1 hour) has passed

### Example Timeline:
```
10:00 AM - Bot posts status message
10:15 AM - Bot restarts
          → Finds 15-minute-old message
          → Updates it (doesn't create new) ✅
10:30 AM - Bot continues updating same message
11:00 AM - 1 hour passed since message created
          → Creates new message (expected behavior)
```

## Configuration

The refresh interval is controlled by `STATUS_MESSAGE_REFRESH_INTERVAL` in config:

```python
# In nebulous_bot/config.py
STATUS_MESSAGE_REFRESH_INTERVAL = 3600  # 1 hour in seconds
```

Change this value to adjust how often new status messages are posted.

## Testing

**Test 1: Bot restart with recent message**
1. Start bot, wait 10 minutes
2. Restart bot
3. Verify: No new message created, existing message updated

**Test 2: Bot restart with old message**
1. Post a status message
2. Wait 2 hours (or change refresh interval to 1 minute for faster testing)
3. Restart bot
4. Verify: New message created (expected)

**Test 3: Normal operation**
1. Start bot
2. Observe status message updates every 30 seconds
3. After 1 hour, verify new message is posted
4. Repeat cycle

## Impact

✅ **Fixed:** No more duplicate status messages on bot restart  
✅ **Improved:** Better message history (less clutter)  
✅ **Maintained:** Same update frequency (30 seconds)  
✅ **Maintained:** Same refresh interval (1 hour default)  

## Files Changed

- `nebulous_bot/server_monitor.py` - Lines 283-292 (added tracking save on message found)

Both `main.py` and Django `runbot` command benefit from this fix since they share the same `ServerMonitor` class.


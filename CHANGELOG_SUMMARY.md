# Changelog Summary

## 2.3.0 Highlights

- `!listservers` now includes PTB servers by default and respects saved PTB/all filters when the bot refreshes tracked messages. Added `ptb` filter flag.
- `!nextgame` supports `--skip` to ignore lobbies that were already active, and PTB filtering is carried through notifications.
- New `!graph` command renders 7-day player/server/lobby graphs from `PlayerSnapshot` data using `GraphGenerator`.
- New `!formation` command integrates the standalone formation optimizer (with tests and sample fleets) to compact fleets and optionally generate GIF animations.
- Command usage is logged via `CommandLog` (new model + migrations) using lightweight before/after hooks.
- Server monitor updates tracked messages concurrently, falls back when the all-servers fetch fails, and keeps PTB flags in sync after stable-version detection.
- Steam server rule lookups now run off the event loop with timeouts to avoid Discord latency spikes.
- Azure deployment script now uses timestamped tags, verifies revision creation, and warns if persistence isn’t configured; new verify/fix scripts added. Startup script hardens SQLite lock handling and persistence checks.
- Added Oracle deployment guides/scripts plus quick-start and persistence documentation.

Previous PTB/stable-version detection notes are kept below for context.

## Test Branch Detection and PTB Support (earlier release)

### Features Added

1. **Dynamic Stable Version Detection**
   - Stable version is automatically determined from the majority of servers
   - Calculated immediately on first server fetch
   - Recalculated once per day when daily status message is posted
   - Servers with versions higher than stable are marked as test branch (PTB)

2. **Test Branch Server Indicators**
   - PTB servers display 🧪 emoji indicator in server list
   - PTB servers show "Version: X.X.X (Test Branch)" in server details
   - Only visible when server version is ahead of stable version

3. **!nextgame ptb Command**
   - Added support for `!nextgame ptb` to notify users only for PTB servers
   - PTB preference stored per user
   - Notifications filtered by PTB status
   - Can see PTB mode status in "Already Waiting" message

4. **!listservers all Command**
   - Added support for `!listservers all` to display all servers
   - Includes empty servers (0 players)
   - Includes private/password-protected servers
   - Includes servers with bots
   - Can combine with other filters (e.g., `!listservers all lobby`)

### Technical Changes

**nebulous_bot/steam_api.py:**
- Added `include_all` parameter to `get_game_servers()` method
- Updated `_parse_server_data_with_rules()` to skip filtering when `include_all=True`
- Added `set_stable_version()` method to update stable version dynamically
- Updated `_is_test_branch_server()` to use dynamic stable version instead of hardcoded
- Added `_compare_versions()` helper method for semantic version comparison
- Extract version from server rules (preferred over Steam API)

**nebulous_bot/server_monitor.py:**
- Added `stable_version` attribute to track determined stable version
- Added `cached_all_servers` to store unfiltered server list
- Added `_determine_stable_version()` method to calculate from majority
- Updated `_update_server_list()` to fetch both filtered and unfiltered servers
- Updated `add_next_game_waiter()` to accept `ptb_only` parameter
- Updated `find_matching_servers_for_notification()` to filter by PTB when needed
- Updated `_notify_next_game_waiters()` to group by PTB preference and filter accordingly
- Updated `notify_single_user_immediately()` to respect PTB preference

**nebulous_bot/server_formatter.py:**
- Added `TEST_BRANCH_EMOJI = "🧪"` constant
- Updated `get_status_icons()` to include PTB indicator
- Updated `create_server_field_value()` to show version info for PTB servers

**main.py:**
- Updated `nextgame` command to accept `ptb` parameter
- Updated `listservers` command to accept `all` parameter
- Added PTB mode indicators in confirmation messages
- Updated filter help text to include new options

**nebulous_bot/management/commands/runbot.py:**
- Applied same changes as main.py for Django deployment consistency

### Behavior Changes

- Stable version detection: Now automatic and dynamic instead of hardcoded
- Server filtering: Can now bypass all filters with `!listservers all`
- Next game notifications: Can filter to PTB servers only
- Server display: PTB servers show clear visual indicators

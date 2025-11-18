# Nebulous: Fleet Command Discord Server Bot

A Discord bot that monitors and displays server information for **Nebulous: Fleet Command** using the Steam API. The bot provides real-time server status updates and supports various commands to help players find active servers and open lobbies.

## 🐳 Django + Azure Container Deployment

This bot now supports **Django framework** and **containerized Azure deployment**! 

- ✅ Production-ready Django application
- ✅ Docker containerization
- ✅ Azure Container Apps deployment
- ✅ Health checks and monitoring
- ✅ Database models for logging

### 📚 Documentation Quick Links

- **📖 [INDEX.md](INDEX.md)** - Complete documentation index and navigation
- **🚀 [QUICKSTART.md](QUICKSTART.md)** - Get started quickly with any deployment method
- **🔄 [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Upgrade from standalone to Django
- **☁️ [README_DJANGO.md](README_DJANGO.md)** - Django, Docker, and Azure deployment
- **📊 [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)** - What changed in the conversion

**👉 New to the project? Start with [INDEX.md](INDEX.md) or [QUICKSTART.md](QUICKSTART.md)**

The instructions below are for the standalone Python version. Both versions are fully functional and backward compatible.

## Features

🚀 **Real-time Server Monitoring**
- Automatically updates server status every 30 seconds
- Displays active servers with player counts, maps, and game modes
- Maintains a persistent status message that updates automatically
- **Live updating messages**: Last 10 bot messages per channel stay up-to-date automatically
- **Multi-server support**: Use the bot across multiple Discord servers simultaneously

🔔 **Player Threshold Notifications**
- Sends notifications when player count exceeds a configurable threshold
- Role-based opt-in system for notifications
- Prevents notification spam with configurable cooldown intervals
- Shows open lobbies in notification messages

🎮 **Discord Commands**
- `!listservers` - List all active servers with filtering options
- `!openlobbies` - Show servers with available player slots
- `!nextgame` - Get notified when a game is ready (one-time ping)
- `!refresh` - Force update server information
- `!status` - Display bot status and information
- `!stats` - View game statistics (all-time, today, week, month)
- `!mapstats` - View map play frequency statistics
- `!serverstats` - View server usage statistics

📈 **Statistics Tracking** (NEW!)
- Persistent database storage of game sessions and player activity
- Tracks games played (lobby → in-game 5+ mins → debrief)
- Player count history with 5-minute snapshots
- Map frequency analysis (most played maps)
- Server usage metrics (most active servers)
- Detailed statistics via Discord commands

📊 **Rich Information Display**
- Server player counts and capacity
- Current map and game mode
- Server security status (VAC, password protection)
- Ping information and server addresses

## Installation

### Prerequisites

- Python 3.8 or higher
- A Discord bot token
- A Steam Web API key

### Setup Steps

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd NebulousServerDiscordBot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create environment configuration**
   Create a `.env` file in the project root with the following variables:
   
   ```env
   # Discord Bot Configuration
   DISCORD_TOKEN=your_discord_bot_token_here
   APPLICATION_ID=your_application_id_here
   
   # Server Configuration (JSON format)
   # For a single server:
   SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321}]
   
   # With notifications enabled (optional):
   # SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321, "notification_channel_id": 0987654321, "notification_role_id": 1122334455}]
   
   # For multiple servers:
   # SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321}, {"guild_id": 1111111111, "status_channel_id": 2222222222}]
   
   # Steam API Configuration
   STEAM_API_KEY=your_steam_api_key_here
   
   # Optional: Notification Configuration
   # PLAYER_THRESHOLD=40  # Minimum players to trigger notification
   # NOTIFICATION_INTERVAL=3600  # Minimum seconds between notifications (1 hour)
   ```

4. **Get required credentials**

   **Discord Bot Token:**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to "Bot" section and create a bot
   - Copy the bot token

   **Steam API Key:**
   - Go to [Steam Web API Key](https://steamcommunity.com/dev/apikey)
   - Register for an API key using your Steam account
   - Copy the API key

   **Discord IDs:**
   - Enable Developer Mode in Discord (User Settings > Advanced > Developer Mode)
   - Right-click your Discord server name → Copy ID (for `guild_id`)
   - Right-click the channel where you want status updates → Copy ID (for `status_channel_id`)
   - For the APPLICATION_ID, copy the Application ID from the Discord Developer Portal's General Information page

5. **Run the bot**
   ```bash
   python main.py
   ```

## Migration Guide (Existing Users)

If you're upgrading from a previous version that used `DISCORD_GUILD_ID` and `STATUS_CHANNEL_ID`, you need to migrate to the new `SERVER_CONFIGS` format:

### Migration Steps

1. **Backup your existing `.env` file**

2. **Convert your configuration** from:
   ```env
   DISCORD_GUILD_ID=1400973312963645551
   STATUS_CHANNEL_ID=1400976297408069682
   ```
   
   To:
   ```env
   SERVER_CONFIGS=[{"guild_id": 1400973312963645551, "status_channel_id": 1400976297408069682}]
   ```

3. **For multiple servers**, add more entries to the JSON array:
   ```env
   SERVER_CONFIGS=[{"guild_id": 1400973312963645551, "status_channel_id": 1400976297408069682}, {"guild_id": 2222222222, "status_channel_id": 3333333333}]
   ```

4. **(Optional) Add notification settings** to enable player threshold alerts:
   ```env
   SERVER_CONFIGS=[{"guild_id": 1400973312963645551, "status_channel_id": 1400976297408069682, "notification_channel_id": 1400976297408069682, "notification_role_id": 1234567890123456789}]
   ```

**Important Notes:**
- The entire `SERVER_CONFIGS` value must be on a single line
- Each Discord server needs its own status channel ID where the bot will post updates
- The old `DISCORD_GUILD_ID`/`STATUS_CHANNEL_ID` format is no longer supported
- `notification_channel_id` and `notification_role_id` are optional fields for player threshold notifications

## Configuration Options

The bot can be configured through environment variables or by modifying `config.py`:

| Variable | Description | Default |
|----------|-------------|---------|
| `UPDATE_INTERVAL` | Server update frequency (seconds) | 30 |
| `STATUS_MESSAGE_REFRESH_INTERVAL` | Time between creating new status messages (seconds) | 86400 (24 hours) |
| `MAX_SERVERS_DISPLAY` | Maximum servers to show in status | 20 |
| `COMMAND_PREFIX` | Bot command prefix | ! |
| `PLAYER_THRESHOLD` | Minimum players to trigger notification | 40 |
| `NOTIFICATION_INTERVAL` | Minimum seconds between notifications | 3600 (1 hour) |

### Player Threshold Notifications Setup

To enable player count notifications:

1. **Create a notification role** in your Discord server (e.g., "Nebulous Notifications")
2. **Get the role ID**: Right-click the role → Copy ID (requires Developer Mode)
3. **Get the notification channel ID**: Right-click the channel → Copy ID
4. **Add to your SERVER_CONFIGS**:
   ```env
   SERVER_CONFIGS=[{"guild_id": 1234567890, "status_channel_id": 0987654321, "notification_channel_id": 0987654321, "notification_role_id": 1122334455}]
   ```
5. **Users can opt-in** by assigning themselves the notification role
6. **Customize thresholds** (optional):
   ```env
   PLAYER_THRESHOLD=40  # Alert when 40+ players are online
   NOTIFICATION_INTERVAL=3600  # Wait at least 1 hour between alerts
   ```

**Note**: The notification will only be sent once per interval, even if player count drops below the threshold and rises again. This prevents notification spam.

## Commands

### `!listservers [filters]`
**Aliases:** `!ls`, `!servers`

Lists all active Nebulous: Fleet Command servers with optional filtering.

**Available Filters:**
- `open` - Only servers with available slots
- `full` - Only full servers
- `empty` - Only empty servers  
- `nopassword` - Only servers without password protection

**Examples:**
```
!listservers
!listservers open
!listservers open nopassword
!ls full
```

### `!openlobbies`
**Aliases:** `!open`, `!available`

Shows only servers that have available player slots, sorted by most available slots first.

### `!refresh`
**Aliases:** `!update`

Forces an immediate update of the server list, bypassing the normal 30-second interval.

### `!status`
**Aliases:** `!info`

Displays bot status information including:
- Server monitoring status
- Number of tracked servers
- Last update time
- Available commands

## Bot Permissions

The bot requires the following Discord permissions:
- Read Messages
- Send Messages
- Embed Links
- Use External Emojis
- Read Message History
- Mention Roles (optional, required for player threshold notifications)

## Live Updating Messages

The bot provides two types of live-updating messages:

### 1. Persistent Status Message

The bot maintains a persistent status message in the configured channel(s) that updates automatically every 30 seconds. A new status message is created once per day (configurable). This message shows:

- Current active servers
- Player counts and server capacity
- Maps and game modes
- Server security indicators (🔒 for password, 🛡️ for VAC)
- Total player summary

### 2. Command Response Tracking

When you use commands like `!listservers` or `!openlobbies`, the bot automatically tracks the last **10 messages per channel** and keeps them updated every 30 seconds with fresh data. This means:

- ✅ No need to spam commands for updates
- ✅ Multiple users can see the same live data
- ✅ Server information stays current automatically
- ✅ Old messages (beyond 10) are automatically removed from tracking

**Example**: Run `!listservers` three times, and all three messages will update automatically every 30 seconds!

### Multi-Server Support

The bot can now operate across multiple Discord servers simultaneously! Each configured Discord server will receive its own status message in its designated channel. To add multiple servers, use the `SERVER_CONFIGS` format in your `.env` file as shown in the setup instructions.

## API Integration

### Steam API Notes

Currently, the bot includes both real Steam API integration and a mock API for testing:

- **Production**: Change `MockSteamAPI()` to `SteamAPI()` in `server_monitor.py`
- **Testing**: Uses `MockSteamAPI()` to generate sample server data

The Steam Web API has limitations compared to the Steamworks SDK. The current implementation may need adjustments based on available Steam API endpoints for server querying.

### Nebulous: Fleet Command

- **Steam App ID**: 887570
- **Game Name**: Nebulous: Fleet Command

## Logging

The bot creates detailed logs in:
- `nebulous_bot.log` - File logging
- Console output - Real-time logging

Log levels include INFO, WARNING, and ERROR messages for monitoring bot health and troubleshooting.

## Error Handling

The bot includes comprehensive error handling for:
- Network connectivity issues
- Discord API rate limits
- Steam API failures
- Configuration validation
- Command processing errors

## Development

### Project Structure

```
NebulousServerDiscordBot/
├── main.py              # Main bot application
├── config.py            # Configuration management
├── steam_api.py         # Steam API integration
├── server_monitor.py    # Server monitoring logic
├── requirements.txt     # Python dependencies  
├── README.md           # This file
└── .env                # Environment variables (create this)
```

### Adding Features

To extend the bot functionality:

1. **New Commands**: Add command functions in `main.py`
2. **Steam API**: Modify `steam_api.py` for additional data
3. **Monitoring**: Enhance `server_monitor.py` for new features
4. **Configuration**: Update `config.py` for new settings

### Testing

The bot includes a `MockSteamAPI` class for testing without requiring Steam API access. This generates realistic server data for development and testing purposes.

## Troubleshooting

### Common Issues

**Bot doesn't respond to commands:**
- Check Discord permissions
- Verify bot token is correct
- Ensure message content intent is enabled

**No server data displayed:**
- Verify Steam API key is valid
- Check network connectivity
- Review bot logs for API errors

**Status message not updating:**
- Confirm status channel IDs are correct in your configuration
- Check bot has write permissions in all configured channels
- Verify the channels exist and bot can access them
- For multi-server setup, ensure SERVER_CONFIGS JSON is properly formatted

**Configuration errors:**
- Ensure all required environment variables are set (`DISCORD_TOKEN`, `APPLICATION_ID`, `SERVER_CONFIGS`, `STEAM_API_KEY`)
- Check `.env` file syntax and location (SERVER_CONFIGS JSON must be on a single line)
- Verify Discord and Steam credentials are valid
- Ensure SERVER_CONFIGS JSON format is valid (use online JSON validator if needed)
- Format: `SERVER_CONFIGS=[{"guild_id": 123, "status_channel_id": 456}]`

### Support

For issues and questions:
1. Check the bot logs in `nebulous_bot.log`
2. Verify all configuration variables are set correctly
3. Test with mock API first before using real Steam API
4. Review Discord bot permissions and channel access

## License

This project is open source. Please check the repository for license details.

---

**Note**: This bot is not affiliated with Eridanus Industries (developers of Nebulous: Fleet Command) or Valve Corporation. It uses publicly available APIs to provide server information to the gaming community. 
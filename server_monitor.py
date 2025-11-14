import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import discord
from nebulous_bot.steam_api import SteamAPI
from nebulous_bot.config import Config

# PST timezone
PST = timezone(timedelta(hours=-8))

logger = logging.getLogger(__name__)

class ServerMonitor:
    def __init__(self, bot):
        self.bot = bot
        self.steam_api = SteamAPI()  # Using real Steam API now
        self.last_update = None
        self.cached_servers = []
        
        # Multi-server support: track status messages per guild
        # Format: {guild_id: {'message': Message, 'created_at': datetime}}
        self.status_messages = {}
        
        # Track player threshold notifications per guild
        # Format: {guild_id: {'last_notification_time': datetime, 'last_player_count': int}}
        self.notification_state = {}
        
        self.monitoring_task = None
        
        # Formatter will be set by main.py to avoid duplicate instances
        self.formatter = None
        
        # Track state transition times for servers
        # Format: {server_id: {'transition_time': datetime, 'previous_status': str, 'current_state': str}}
        self.game_start_times = {}
    
    def set_formatter(self, formatter):
        """Set the formatter instance to use for embed creation"""
        self.formatter = formatter
        
    async def start_monitoring(self):
        """Start the server monitoring loop"""
        if self.monitoring_task is None or self.monitoring_task.done():
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            logger.info("Server monitoring started")
    
    async def stop_monitoring(self):
        """Stop the server monitoring loop"""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            logger.info("Server monitoring stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop that runs every UPDATE_INTERVAL seconds"""
        logger.info(f"Monitoring loop started - will update every {Config.UPDATE_INTERVAL} seconds")
        iteration = 0
        while True:
            try:
                iteration += 1
                logger.info(f"Monitoring loop iteration {iteration} starting...")
                
                await self._update_server_list()
                logger.debug(f"Server list updated: {len(self.cached_servers)} servers")
                
                await self._update_status_message()
                logger.info(f"📤 Status message update cycle completed")
                
                await self._check_and_send_notifications()
                logger.debug("Notifications checked")
                
                logger.info(f"Monitoring loop iteration {iteration} complete. Sleeping {Config.UPDATE_INTERVAL}s...")
                await asyncio.sleep(Config.UPDATE_INTERVAL)
            except asyncio.CancelledError:
                logger.info("Monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop iteration {iteration}: {e}", exc_info=True)
                await asyncio.sleep(Config.UPDATE_INTERVAL)
    
    async def _update_server_list(self):
        """Fetch latest server information from Steam API with server rules"""
        try:
            logger.debug("Fetching servers from Steam API...")
            async with self.steam_api as api:
                servers = await api.get_game_servers()
                
                logger.debug(f"Received {len(servers)} servers from Steam API")
                
                # Track state transitions and game start times
                await self._track_game_start_times(servers)
                
                # Servers now come with real status from server rules
                self.cached_servers = servers
                self.last_update = datetime.now()
                
                # Log stats
                total_servers = len(servers)
                active_players = sum(s.get('players', 0) for s in servers)
                open_lobbies = len(self.get_open_lobbies())
                in_game = len([s for s in servers if s.get('status') == 'in_game'])
                
                logger.info(f"✅ Updated server list at {self.last_update.strftime('%H:%M:%S')}: {total_servers} servers, {active_players} players, {open_lobbies} open lobbies, {in_game} in-game")
                
        except Exception as e:
            logger.error(f"❌ Failed to update server list: {e}", exc_info=True)
    
    async def _track_game_start_times(self, servers: List[Dict]):
        """Track when servers transition from lobby to in-game and record game start times"""
        current_time = datetime.now(PST)  # Use PST timezone
        
        for server in servers:
            server_id = server.get('id', server.get('address', ''))
            if not server_id:
                continue
                
            current_status = server.get('status', 'lobby')
            previous_info = self.game_start_times.get(server_id, {})
            previous_status = previous_info.get('previous_status', 'lobby')
            
            # Detect transition from lobby to in_game or debrief
            if (previous_status == 'lobby' and current_status in ['in_game', 'debrief']) or \
               (previous_status == 'in_game' and current_status == 'debrief'):
                self.game_start_times[server_id] = {
                    'transition_time': current_time,
                    'previous_status': current_status,
                    'current_state': current_status,
                    'server_name': server.get('name', 'Unknown')
                }
                state_names = {'in_game': 'Game started', 'debrief': 'Entered debrief'}
                logger.info(f"{state_names.get(current_status, 'State changed')} on '{server.get('name', 'Unknown')}' at {current_time.strftime('%H:%M:%S PST')}")
            
            # Update previous status for next check
            elif server_id in self.game_start_times:
                self.game_start_times[server_id]['previous_status'] = current_status
                self.game_start_times[server_id]['current_state'] = current_status
            else:
                # First time seeing this server
                self.game_start_times[server_id] = {
                    'transition_time': None,
                    'previous_status': current_status,
                    'current_state': current_status,
                    'server_name': server.get('name', 'Unknown')
                }
            
            # Clean up old transition times for servers that are back in lobby
            if current_status == 'lobby' and previous_info.get('transition_time') is not None:
                # Game ended, clear the transition time but keep tracking
                self.game_start_times[server_id]['transition_time'] = None
        
        # Clean up entries for servers that no longer exist
        current_server_ids = {server.get('id', server.get('address', '')) for server in servers}
        old_server_ids = set(self.game_start_times.keys()) - current_server_ids
        for old_id in old_server_ids:
            del self.game_start_times[old_id]
    
    # TODO Check Duplication: Game timing methods moved to ServerFormatter to eliminate circular dependency
    
    async def _update_status_message(self):
        """Update the persistent status message in Discord (create new one every hour)"""
        if not Config.SERVER_CONFIGS or not self.formatter:
            return
        
        # Update status message for each configured server
        for server_config in Config.SERVER_CONFIGS:
            await self._update_status_message_for_server(server_config)
    
    async def _update_status_message_for_server(self, server_config: Dict):
        """Update the status message for a specific Discord server"""
        guild_id = server_config['guild_id']
        status_channel_id = server_config['status_channel_id']
        
        try:
            channel = self.bot.get_channel(status_channel_id)
            if not channel:
                logger.error(f"Status channel {status_channel_id} (guild {guild_id}) not found")
                return
                
            embed = self._create_server_status_embed(self.formatter)
            now = datetime.now()
            
            # Get or initialize status message tracking for this guild
            guild_status = self.status_messages.get(guild_id, {})
            status_message = guild_status.get('message')
            status_message_created_at = guild_status.get('created_at')
            
            # If no status message is tracked (bot restart), try to find the most recent bot message
            if status_message is None:
                status_message, status_message_created_at = await self._find_recent_bot_message(channel, now)
                if status_message:
                    logger.info(f"Found existing status message (ID: {status_message.id}) from {status_message_created_at} for guild {guild_id}")
            
            # Check if we need to create a new message (based on configured interval or if no message exists)
            should_create_new = (
                status_message is None or
                status_message_created_at is None or
                (now - status_message_created_at).total_seconds() >= Config.STATUS_MESSAGE_REFRESH_INTERVAL
            )
            
            if should_create_new:
                # Create new status message
                status_message = await channel.send(embed=embed)
                self.status_messages[guild_id] = {
                    'message': status_message,
                    'created_at': now
                }
                logger.info(f"Created new status message for guild {guild_id}")
            else:
                # Update existing message
                try:
                    await status_message.edit(embed=embed)
                    logger.info(f"✅ Updated existing status message for guild {guild_id}")
                except discord.NotFound:
                    # Message was deleted, create a new one
                    status_message = await channel.send(embed=embed)
                    self.status_messages[guild_id] = {
                        'message': status_message,
                        'created_at': now
                    }
                    logger.info(f"Previous message not found, created new status message for guild {guild_id}")
                except discord.HTTPException as e:
                    logger.error(f"❌ Discord HTTP error updating status message for guild {guild_id}: {e}")
                    # Don't try to create a new message immediately - wait for next cycle
                    # This prevents message spam if there's a temporary connection issue
                except Exception as e:
                    logger.error(f"❌ Unexpected error updating status message for guild {guild_id}: {e}", exc_info=True)
                    # Mark the message as invalid so we create a new one next cycle
                    self.status_messages[guild_id] = {
                        'message': None,
                        'created_at': None
                    }
                    
        except Exception as e:
            logger.error(f"Error updating status message for guild {guild_id}: {e}")
    
    async def _find_recent_bot_message(self, channel, current_time: datetime) -> tuple[Optional[discord.Message], Optional[datetime]]:
        """
        Search for the bot's most recent message in the channel.
        Returns (message, created_at) if found within time range, else (None, None)
        """
        try:
            # Search through recent messages in the channel
            # Limit search to messages within the refresh interval window
            time_limit = current_time - timedelta(seconds=Config.STATUS_MESSAGE_REFRESH_INTERVAL)
            
            # Discord's history() fetches messages in reverse chronological order (newest first)
            async for message in channel.history(limit=100):
                # Check if this is a message from the bot
                if message.author.id == self.bot.user.id:
                    # Check if message has an embed (our status messages always have embeds)
                    if message.embeds:
                        # Only match persistent status messages, not command responses
                        embed = message.embeds[0]
                        if embed.title and "Live Server Status" in embed.title:
                            # Check if the message is within the time range
                            if message.created_at.replace(tzinfo=None) >= time_limit:
                                logger.info(f"Found recent status message from {message.created_at}")
                                return message, message.created_at.replace(tzinfo=None)
                            else:
                                # Message is too old, no point searching further
                                logger.info(f"Found status message but it's too old ({message.created_at}), creating new one")
                                return None, None
            
            # No suitable message found
            logger.info("No recent status message found in channel, will create new one")
            return None, None
            
        except discord.Forbidden:
            logger.error(f"No permission to read message history in channel {channel.id}")
            return None, None
        except Exception as e:
            logger.error(f"Error searching for recent bot message: {e}")
            return None, None
    
    async def _check_and_send_notifications(self):
        """Check if player count exceeds threshold and send notifications if needed"""
        # Calculate total active players across all servers
        total_players = sum(server.get('players', 0) for server in self.cached_servers)
        
        # Check notifications for each configured server
        for server_config in Config.SERVER_CONFIGS:
            await self._check_and_send_notification_for_server(server_config, total_players)
    
    async def _check_and_send_notification_for_server(self, server_config: Dict, total_players: int):
        """Check and send notification for a specific Discord server"""
        guild_id = server_config['guild_id']
        notification_channel_id = server_config.get('notification_channel_id')
        notification_role_id = server_config.get('notification_role_id')
        
        # Skip if notification is not configured for this server
        if not notification_channel_id:
            return
        
        try:
            # Check if we should send a notification
            now = datetime.now()
            guild_notification_state = self.notification_state.get(guild_id, {})
            last_notification_time = guild_notification_state.get('last_notification_time')
            
            # Determine if threshold is exceeded
            threshold_exceeded = total_players >= Config.PLAYER_THRESHOLD
            
            # Determine if enough time has passed since last notification
            time_since_last_notification = None
            if last_notification_time:
                time_since_last_notification = (now - last_notification_time).total_seconds()
            
            should_notify = (
                threshold_exceeded and
                (last_notification_time is None or 
                 time_since_last_notification >= Config.NOTIFICATION_INTERVAL)
            )
            
            if should_notify:
                # Send notification
                channel = self.bot.get_channel(notification_channel_id)
                if not channel:
                    logger.error(f"Notification channel {notification_channel_id} (guild {guild_id}) not found")
                    return
                
                # Build the notification message
                message_parts = []
                
                # Add role mention if configured
                if notification_role_id:
                    message_parts.append(f"<@&{notification_role_id}>")
                
                # Add the notification text
                open_lobbies = len(self.get_open_lobbies())
                message_parts.append(
                    f"🎮 **{total_players} players** are currently online! "
                    f"{'**' + str(open_lobbies) + ' open lobbies** available!' if open_lobbies > 0 else 'Time to start a game!'}"
                )
                
                message = " ".join(message_parts)
                
                # Send the notification
                await channel.send(message)
                
                # Update notification state
                self.notification_state[guild_id] = {
                    'last_notification_time': now,
                    'last_player_count': total_players
                }
                
                logger.info(f"Sent player threshold notification to guild {guild_id}: {total_players} players online")
        
        except Exception as e:
            logger.error(f"Error sending notification for guild {guild_id}: {e}")
    
    def _create_server_status_embed(self, formatter) -> discord.Embed:
        """Create Discord embed with current server status"""
        # TODO Check Duplication: Replaced with centralized formatter - verify formatting matches expectations
        return formatter.create_status_embed(self.cached_servers, self.last_update, self.game_start_times)
    
    def get_open_lobbies(self) -> List[Dict]:
        """Get servers that are open for joining (lobby state, not at map capacity)"""
        return [
            server for server in self.cached_servers
            if (server.get('status') == 'lobby' and 
                server.get('players', 0) < server.get('map_capacity', 8))
        ]
    
    def get_servers_by_criteria(self, **criteria) -> List[Dict]:
        """Filter servers by various criteria"""
        filtered_servers = self.cached_servers.copy()
        
        for key, value in criteria.items():
            if key == 'has_players':
                filtered_servers = [s for s in filtered_servers if (s.get('players', 0) > 0) == value]
            elif key == 'open_lobby':
                # Only servers in lobby state and accepting players
                # Use map capacity instead of server max capacity
                if value:
                    filtered_servers = [s for s in filtered_servers if 
                                  (s.get('status') == 'lobby' and s.get('players', 0) < s.get('map_capacity', 8)) == value]
            elif key == 'no_password':
                filtered_servers = [s for s in filtered_servers if (not s.get('has_password', False)) == value]
            elif key == 'map':
                filtered_servers = [s for s in filtered_servers if s.get('map', '').lower() == value.lower()]
            elif key == 'game_mode':
                filtered_servers = [s for s in filtered_servers if s.get('game_mode', '').lower() == value.lower()]
            elif key == 'region':
                filtered_servers = [s for s in filtered_servers if s.get('region', '').lower() == value.lower()]
            elif key == 'status':
                filtered_servers = [s for s in filtered_servers if s.get('status', '') == value]
        
        return filtered_servers
    
    async def force_update(self):
        """Force an immediate update of server data"""
        await self._update_server_list()
        await self._update_status_message()
        logger.info("Forced server update completed") 
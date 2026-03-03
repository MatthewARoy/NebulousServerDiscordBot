import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import List, Dict, Optional, Any, Tuple
import discord
from nebulous_bot.steam_api import SteamAPI
from nebulous_bot.config import Config
from nebulous_bot.statistics_tracker import StatisticsService

# PST timezone
PST = timezone(timedelta(hours=-8))

logger = logging.getLogger(__name__)

class ServerMonitor:
    URL_HOST_PATTERN = re.compile(r'(?<!@)\b([a-z0-9][a-z0-9-]{0,62})\.([a-z]{2,24})(?=(?:/|\b))', re.IGNORECASE)

    def __init__(self, bot):
        self.bot = bot
        self.steam_api = SteamAPI()  # Using real Steam API now
        self.last_update = None
        self.cached_servers = []
        
        # Multi-server support: track status messages per guild
        # Format: {guild_id: {'message': Message, 'created_at': datetime}}
        self.status_messages = {}
        
        # Track the last 3 bot messages per channel for live updates
        # Format: {channel_id: [{'message': Message, 'created_at': datetime}, ...]}
        self.tracked_messages = {}
        self.max_tracked_messages = 3
        
        # Track player threshold notifications per guild
        # Format: {guild_id: {'last_notification_time': datetime, 'last_player_count': int}}
        self.notification_state = {}
        
        self.monitoring_task = None
        self.health_check_task = None  # Self-healing health check
        self.tracked_update_task = None  # Background task for updating tracked messages
        
        # Formatter will be set by main.py to avoid duplicate instances
        self.formatter = None
        
        # Track state transition times for servers
        # Format: {server_id: {'transition_time': datetime, 'previous_status': str, 'current_state': str}}
        self.game_start_times = {}
        
        # Statistics tracking service
        self.statistics_service = StatisticsService()
        
        # Track users waiting for next game notifications
        # Format: {(user_id, ptb_only): {'channel_id': int, 'timestamp': datetime, 'username': str, ...}}
        self.next_game_waiters = {}
        
        # Track daily queue alert checks for !nextgame (PST date of last check)
        self.last_next_game_queue_alert_check_date = None
        
        # Track servers that just entered debriefing in the current cycle
        # Format: {server_id: server_dict}
        self.recent_debrief_transitions = {}
        
        # Stable version determined from majority of servers
        # Updated when a new daily status message is created
        self.stable_version = None
        
        # Store unfiltered servers for !listservers all command
        self.cached_all_servers = []
    
    def set_formatter(self, formatter):
        """Set the formatter instance to use for embed creation"""
        self.formatter = formatter

    @classmethod
    def sanitize_server_name_for_display(cls, name: Any) -> str:
        """
        Neutralize URL-like strings in server names so Discord does not auto-link them.
        Example: discord.gg/b -> discord .gg/b
        """
        safe_name = str(name or "Unknown")
        # Break protocol and common URL prefix patterns first.
        safe_name = safe_name.replace("https://", "https ://").replace("http://", "http ://")
        safe_name = re.sub(r'(?i)\bwww\.', 'www .', safe_name)
        # Break hostnames by inserting a space before the TLD dot.
        return cls.URL_HOST_PATTERN.sub(r'\1 .\2', safe_name)
    
    async def track_message(self, message, metadata: Optional[Dict] = None):
        """Track a bot message for automatic updates"""
        channel_id = message.channel.id
        
        if channel_id not in self.tracked_messages:
            self.tracked_messages[channel_id] = []
        
        # Add message to the beginning of the list
        entry = {
            'message': message,
            'created_at': datetime.now(timezone.utc)
        }
        if metadata:
            entry['metadata'] = dict(metadata)
        self.tracked_messages[channel_id].insert(0, entry)
        
        # If we exceed the limit, mark the oldest message as stopped
        if len(self.tracked_messages[channel_id]) > self.max_tracked_messages:
            # Get the message that will be removed
            removed_msg_info = self.tracked_messages[channel_id][self.max_tracked_messages]
            removed_message = removed_msg_info['message']
            
            # Update it one final time with skull emoji
            try:
                if removed_message.embeds:
                    original_embed = removed_message.embeds[0]
                    if original_embed.title:
                        # Replace "@" with "💀" in the title
                        new_title = original_embed.title.replace(" @ ", " 💀 ")
                        
                        # Create a copy of the embed with updated title
                        new_embed = discord.Embed.from_dict(original_embed.to_dict())
                        new_embed.title = new_title
                        
                        # Update the message one final time
                        await removed_message.edit(embed=new_embed)
                        logger.info(f"Marked message {removed_message.id} as stopped (replaced @ with 💀)")
            except Exception as e:
                logger.debug(f"Could not update removed message {removed_message.id}: {e}")
        
        # Keep only the last N messages
        self.tracked_messages[channel_id] = self.tracked_messages[channel_id][:self.max_tracked_messages]
        
        logger.info(f"Now tracking {len(self.tracked_messages[channel_id])} messages in channel {channel_id}")
        
    async def start_monitoring(self):
        """Start the server monitoring loop and health check"""
        if self.monitoring_task is None or self.monitoring_task.done():
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            logger.info("Server monitoring started")
        
        # Start health check if not already running
        if self.health_check_task is None or self.health_check_task.done():
            self.health_check_task = asyncio.create_task(self._health_check_loop())
            logger.info("Health check started")
    
    async def stop_monitoring(self):
        """Stop the server monitoring loop and health check"""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            logger.info("Server monitoring stopped")
        
        if self.health_check_task and not self.health_check_task.done():
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
            logger.info("Health check stopped")

        if self.tracked_update_task and not self.tracked_update_task.done():
            self.tracked_update_task.cancel()
            try:
                await self.tracked_update_task
            except asyncio.CancelledError:
                pass
            logger.info("Tracked message updates stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop that runs every UPDATE_INTERVAL seconds"""
        logger.info(f"Monitoring loop started - will update every {Config.UPDATE_INTERVAL} seconds")
        logger.info(f"Bot is connected to {len(self.bot.guilds)} guilds")
        iteration = 0
        while True:
            try:
                iteration += 1
                logger.info(f"Monitoring loop iteration {iteration} starting...")
                
                await self._update_server_list()
                logger.debug(f"Server list updated: {len(self.cached_servers)} servers")
                
                await self._update_status_message()
                logger.info(f"📤 Status message update cycle completed")
                
                if self.tracked_update_task is None or self.tracked_update_task.done():
                    self.tracked_update_task = asyncio.create_task(self._update_tracked_messages())
                else:
                    logger.debug("Tracked message update already running")
                
                await self._check_and_send_notifications()
                logger.debug("Notifications checked")
                
                await self._update_statistics()
                logger.debug("Statistics updated")
                
                await self._check_next_game_notifications()
                logger.debug("Next game notifications checked")
                
                await self._check_daily_next_game_queue_alert()
                logger.debug("Daily nextgame queue alert checked")
                
                logger.info(f"Monitoring loop iteration {iteration} complete. Sleeping {Config.UPDATE_INTERVAL}s...")
                await asyncio.sleep(Config.UPDATE_INTERVAL)
            except asyncio.CancelledError:
                logger.warning("⚠️ Monitoring loop cancelled - this should only happen on bot shutdown")
                raise  # Re-raise so the task shows as cancelled
            except Exception as e:
                logger.error(f"❌ CRITICAL: Error in monitoring loop iteration {iteration}: {e}", exc_info=True)
                logger.error(f"Exception type: {type(e).__name__}")
                logger.error(f"Exception args: {e.args}")
                # Continue running even after errors
                logger.info(f"Continuing monitoring loop despite error. Sleeping {Config.UPDATE_INTERVAL}s...")
                await asyncio.sleep(Config.UPDATE_INTERVAL)
        
        logger.error("❌ CRITICAL: Monitoring loop exited unexpectedly!")
    
    async def _health_check_loop(self):
        """Self-healing health check that restarts monitoring if it stops"""
        logger.info("Health check loop started - checking every 60 seconds")
        await asyncio.sleep(60)  # Wait 1 minute before first check
        
        while True:
            try:
                # Check if monitoring task is still running
                if self.monitoring_task is None or self.monitoring_task.done():
                    logger.error("⚠️ HEALTH CHECK: Monitoring loop has stopped! Attempting restart...")
                    
                    # Log the reason if possible
                    if self.monitoring_task and self.monitoring_task.done():
                        try:
                            exc = self.monitoring_task.exception()
                            if exc:
                                logger.error(f"Monitoring loop exception: {exc}")
                            else:
                                logger.error("Monitoring loop exited cleanly (no exception)")
                        except:
                            pass
                    
                    # Restart the monitoring loop
                    self.monitoring_task = asyncio.create_task(self._monitoring_loop())
                    logger.info("✅ HEALTH CHECK: Monitoring loop restarted")
                else:
                    logger.debug("Health check: Monitoring loop is running")
                
                # Sleep for 1 minute before next check
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                logger.info("Health check loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in health check loop: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def _update_server_list(self):
        """Fetch latest server information from Steam API with server rules"""
        try:
            logger.debug("Fetching servers from Steam API...")
            async with self.steam_api as api:
                # Get filtered servers (default behavior)
                servers = await api.get_game_servers()
                
                # Also get all servers for !listservers all command
                all_servers = await api.get_game_servers(include_all=True)

                # Fallback: if all_servers failed, use filtered list so !listservers all is not empty
                if not all_servers and servers:
                    logger.warning("Steam API returned no all_servers; falling back to filtered servers")
                    all_servers = list(servers)
                
                logger.debug(f"Received {len(servers)} filtered servers, {len(all_servers)} total servers from Steam API")
                
                # Track state transitions and game start times
                await self._track_game_start_times(servers)
                
                # Servers now come with real status from server rules
                self.cached_servers = servers
                self.cached_all_servers = all_servers
                self.last_update = datetime.now(timezone.utc)

                # If we already know stable version, reapply PTB flags to both caches
                if self.stable_version:
                    self._recalculate_test_branch_flags()
                
                # If stable version hasn't been determined yet, determine it immediately
                if self.stable_version is None:
                    self._determine_stable_version()
                
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
                
                # Track debrief transitions for nextgame notifications
                if current_status == 'debrief':
                    self.recent_debrief_transitions[server_id] = server
            
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
            now = datetime.now(timezone.utc)
            
            # Get or initialize status message tracking for this guild
            guild_status = self.status_messages.get(guild_id, {})
            status_message = guild_status.get('message')
            status_message_created_at = guild_status.get('created_at')
            
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
            
            # Check if we need to create a new message (based on configured interval or if no message exists)
            should_create_new = (
                status_message is None or
                status_message_created_at is None or
                (now - status_message_created_at).total_seconds() >= Config.STATUS_MESSAGE_REFRESH_INTERVAL
            )
            
            if should_create_new:
                # Determine stable version from majority of servers when creating new daily status message
                # Only recalculate if stable version is already set (once per day refresh)
                # If stable_version is None, it will be determined in _update_server_list
                if self.stable_version is not None:
                    self._determine_stable_version()
                
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
                    # Determine stable version when creating new status message
                    # Only recalculate if stable version is already set (once per day refresh)
                    # If stable_version is None, it will be determined in _update_server_list
                    if self.stable_version is not None:
                        self._determine_stable_version()
                    
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
                            # Ensure both timestamps are timezone-aware for comparison
                            message_time = message.created_at if message.created_at.tzinfo else message.created_at.replace(tzinfo=timezone.utc)
                            
                            # Check if the message is within the time range
                            if message_time >= time_limit:
                                logger.info(f"Found recent status message from {message_time}")
                                return message, message_time
                            else:
                                # Message is too old, no point searching further
                                logger.info(f"Found status message but it's too old ({message_time}), creating new one")
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
    
    async def _update_tracked_messages(self):
        """Update all tracked bot messages with current server data concurrently."""
        if not self.formatter:
            return

        update_tasks = []
        channel_lookup = {}
        removals = defaultdict(list)
        total_updated = 0

        for channel_id, messages in list(self.tracked_messages.items()):
            channel = self.bot.get_channel(channel_id)
            if not channel:
                del self.tracked_messages[channel_id]
                logger.warning(f"Channel {channel_id} no longer accessible, removed tracked messages")
                continue

            channel_lookup[channel_id] = channel
            for idx, msg_info in enumerate(messages):
                update_tasks.append(self._refresh_tracked_message(channel, channel_id, idx, msg_info))

        if not update_tasks:
            return

        results = await asyncio.gather(*update_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error updating tracked message: {result}")
                continue

            channel_id = result['channel_id']
            if result.get('removed'):
                removals[channel_id].append(result['idx'])
                continue

            if result.get('updated'):
                total_updated += 1

        total_removed = 0
        for channel_id, idxs in removals.items():
            messages = self.tracked_messages.get(channel_id)
            if not messages:
                continue
            for idx in sorted(set(idxs), reverse=True):
                if idx < len(messages):
                    del messages[idx]
                    total_removed += 1
            if not messages:
                del self.tracked_messages[channel_id]

        if total_updated > 0 or total_removed > 0:
            logger.info(f"Updated {total_updated} tracked messages, removed {total_removed} deleted messages")

    async def _refresh_tracked_message(self, channel, channel_id: int, idx: int, msg_info: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh a single tracked message and return its update state."""
        message = msg_info['message']
        if not message.embeds:
            return {'channel_id': channel_id, 'idx': idx, 'removed': True}

        original_embed = message.embeds[0]
        original_title = original_embed.title or ""

        if "Live Server Status" in original_title:
            return {'channel_id': channel_id, 'idx': idx, 'updated': False}

        try:
            if "Open Lobbies" in original_title:
                open_servers = self.get_open_lobbies()
                new_embed = self.formatter.create_lobby_list_embed(open_servers, self.last_update)
            elif "Active Servers" in original_title:
                metadata = msg_info.get('metadata', {})
                servers = self._servers_for_listservers_metadata(metadata)
                title_parts = original_title.split(" @ ")
                base_title = title_parts[0] if title_parts else original_title

                update_time = self.last_update or datetime.now(timezone.utc)
                timestamp_int = int(update_time.timestamp())
                time_str = f"<t:{timestamp_int}:R>"
                title_with_time = f"{base_title} @ {time_str}"

                description = f"Found {len(servers)} servers" if servers else "No servers available."
                new_embed = self.formatter.create_server_list_embed(
                    servers, title_with_time, description, max_servers=15,
                    last_update=self.last_update, game_start_times=self.game_start_times
                )
                if original_embed.footer and original_embed.footer.text:
                    new_embed.set_footer(text=original_embed.footer.text)
            else:
                return {'channel_id': channel_id, 'idx': idx, 'updated': False}

            await message.edit(embed=new_embed)
            return {'channel_id': channel_id, 'idx': idx, 'updated': True}

        except discord.NotFound:
            return {'channel_id': channel_id, 'idx': idx, 'removed': True}
        except discord.Forbidden:
            logger.warning(f"No permission to edit message {message.id} in channel {channel_id}")
            return {'channel_id': channel_id, 'idx': idx, 'updated': False}
        except Exception as e:
            logger.error(f"Error updating tracked message {message.id}: {e}")
            return {'channel_id': channel_id, 'idx': idx, 'updated': False}
    
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
            now = datetime.now(timezone.utc)
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
    
    def _recalculate_test_branch_flags(self):
        """Recompute PTB flags for cached server lists using current stable version."""
        if not self.stable_version:
            logger.debug("Cannot recalculate PTB flags: stable_version not set")
            return
        
        ptb_count_cached = 0
        ptb_count_all = 0
        
        for server in self.cached_servers:
            version = server.get('version', '').strip()
            if version:
                old_flag = server.get('is_test_branch', False)
                server['is_test_branch'] = self.steam_api._is_test_branch_server(version)
                if server.get('is_test_branch', False):
                    ptb_count_cached += 1
                    if not old_flag:
                        logger.debug(f"Server {server.get('name', 'Unknown')} ({version}) marked as PTB (stable: {self.stable_version})")
        
        for server in self.cached_all_servers:
            version = server.get('version', '').strip()
            if version:
                old_flag = server.get('is_test_branch', False)
                server['is_test_branch'] = self.steam_api._is_test_branch_server(version)
                if server.get('is_test_branch', False):
                    ptb_count_all += 1
        
        logger.debug(f"Recalculated PTB flags: {ptb_count_cached} PTB in cached_servers, {ptb_count_all} PTB in cached_all_servers (stable_version: {self.stable_version})")
    
    def _determine_stable_version(self):
        """
        Determine the stable version from the majority of servers.
        Called when a new daily status message is created.
        Updates both ServerMonitor and SteamAPI with the determined stable version.
        """
        source_servers = self.cached_all_servers or self.cached_servers
        if not source_servers:
            logger.debug("No servers available to determine stable version")
            return
        
        # Count versions from all servers
        version_counts = {}
        for server in source_servers:
            version = server.get('version', '').strip()
            if version:  # Only count non-empty versions
                version_counts[version] = version_counts.get(version, 0) + 1
        
        if not version_counts:
            logger.debug("No version information available from servers")
            return
        
        # Find the version with the highest count (majority)
        stable_version = max(version_counts.items(), key=lambda x: x[1])[0]
        
        # Only update if we have a clear majority (at least 2 servers with this version)
        if version_counts[stable_version] >= 2:
            # Only update if stable version changed
            if self.stable_version != stable_version:
                self.stable_version = stable_version
                # Update SteamAPI with the stable version so it can detect test branch servers
                self.steam_api.set_stable_version(stable_version)
                logger.info(f"Determined stable version: {stable_version} (from {version_counts[stable_version]} servers)")
                
                # Re-evaluate test branch status for all cached servers with the new stable version
                self._recalculate_test_branch_flags()
        else:
            # Even if we don't have enough servers, if we have at least one version, use it as fallback
            # This ensures PTB detection works even with few servers
            if not self.stable_version and version_counts[stable_version] >= 1:
                self.stable_version = stable_version
                self.steam_api.set_stable_version(stable_version)
                logger.info(f"Determined stable version (fallback): {stable_version} (from {version_counts[stable_version]} server(s))")
                self._recalculate_test_branch_flags()
            else:
                logger.debug(f"Not enough servers to determine stable version (most common: {stable_version} with {version_counts[stable_version]} server(s))")
    
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
    
    def _server_identity(self, server: Dict) -> str:
        """Return unique identity key for a server."""
        return server.get('id') or server.get('address') or server.get('name', '')

    def _get_listservers_base_servers(self, ptb_only: bool, show_all: bool) -> List[Dict]:
        """Return the base server list for !listservers given the filters."""
        if ptb_only:
            # Ensure PTB flags are up to date before filtering
            if self.stable_version:
                self._recalculate_test_branch_flags()
            ptb_servers = [s for s in self.cached_all_servers if s.get('is_test_branch', False)]
            logger.debug(f"PTB filter: found {len(ptb_servers)} PTB servers out of {len(self.cached_all_servers)} total servers (stable_version: {self.stable_version})")
            return ptb_servers
        if show_all:
            return self.cached_all_servers

        base_servers = list(self.cached_servers)
        # Ensure PTB flags are up to date before checking
        if self.stable_version:
            self._recalculate_test_branch_flags()
        ptb_additions = [
            s for s in self.cached_all_servers
            if s.get('is_test_branch', False)
               and s.get('players', 0) > 0
               and self._server_identity(s) not in {self._server_identity(b) for b in base_servers}
        ]
        if ptb_additions:
            base_servers.extend(ptb_additions)
        return base_servers

    def filter_servers(self, base_servers: List[Dict], filters: Dict[str, Any]) -> List[Dict]:
        """Apply dynamic filters (open, region, status, game mode) to a server list."""
        if not filters:
            return base_servers

        filtered_servers = []
        for server in base_servers:
            match = True

            if filters.get('open_lobby'):
                if server.get('status') != 'lobby' or server.get('players', 0) >= server.get('map_capacity', 8):
                    match = False

            if filters.get('status') and server.get('status') != filters['status']:
                match = False

            if filters.get('region') and server.get('region', '').lower() != filters['region'].lower():
                match = False

            if filters.get('game_mode'):
                game_mode = server.get('game_mode', '').lower()
                if filters['game_mode'].lower() == 'competitive' and 'competitive' not in game_mode:
                    match = False
                elif filters['game_mode'].lower() == 'casual' and 'casual' not in game_mode:
                    match = False

            if match:
                filtered_servers.append(server)

        return filtered_servers

    def _servers_for_listservers_metadata(self, metadata: Dict[str, Any]) -> List[Dict]:
        """Rebuild the server list needed for updating a tracked !listservers message."""
        if not metadata or metadata.get('command') != 'listservers':
            return self.cached_servers

        ptb_only = metadata.get('ptb_only', False)
        show_all = metadata.get('show_all', False)
        filters = metadata.get('filters', {}) or {}

        return self.get_servers_for_listservers(ptb_only, show_all, filters)

    def get_servers_for_listservers(self, ptb_only: bool, show_all: bool, filters: Dict[str, Any]) -> List[Dict]:
        """Public helper for commands to rebuild the filtered server list."""
        base_servers = self._get_listservers_base_servers(ptb_only, show_all)
        if filters:
            return self.filter_servers(base_servers, filters)
        return base_servers

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
    
    async def _update_statistics(self):
        """Update statistics tracking with current server data"""
        try:
            # Run statistics update in a thread pool to avoid blocking
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.statistics_service.update, self.cached_servers)
        except Exception as e:
            logger.error(f"Error updating statistics: {e}", exc_info=True)
    
    async def _check_next_game_notifications(self):
        """Check if any waiters should be notified about game availability"""
        if not self.next_game_waiters:
            # Clear recent debrief transitions if no waiters
            self.recent_debrief_transitions.clear()
            return
        
        try:
            # Find matching servers (all servers, filtering happens in notification method)
            trigger_servers = self.find_matching_servers_for_notification(ptb_only=False)
            
            # Notify waiters if any triggers found
            if trigger_servers:
                await self._notify_next_game_waiters(trigger_servers)
                # Clear debrief transitions after notification
                self.recent_debrief_transitions.clear()
        
        except Exception as e:
            logger.error(f"Error checking next game notifications: {e}", exc_info=True)

    async def _check_daily_next_game_queue_alert(self):
        """
        Once per PST day at/after 6pm, check !nextgame queue size.
        If 4+ unique users are queued, ping all queued users by channel.
        This is only an alert and does NOT clear the queue.
        """
        now_pst = datetime.now(PST)
        today = now_pst.date()

        # Run only once per PST day and only at/after 6pm PST.
        if now_pst.hour < 18:
            return
        if self.last_next_game_queue_alert_check_date == today:
            return

        # Mark the day as checked even if queue is too small, to avoid repeated checks.
        self.last_next_game_queue_alert_check_date = today

        unique_user_ids = {user_id for user_id, _ in self.next_game_waiters.keys()}
        queue_size = len(unique_user_ids)
        if queue_size < 4:
            logger.info(
                f"Daily nextgame queue check skipped alert on {today}: "
                f"{queue_size} user(s) queued (< 4 threshold)"
            )
            return

        # Group by channel, dedupe users per channel across queue modes.
        users_by_channel = defaultdict(set)
        for (user_id, _), waiter_info in self.next_game_waiters.items():
            channel_id = waiter_info.get('channel_id')
            if channel_id:
                users_by_channel[channel_id].add(user_id)

        if not users_by_channel:
            logger.warning(
                f"Daily nextgame queue alert on {today} had {queue_size} queued user(s) "
                "but no valid channel IDs were found"
            )
            return

        alert_text = (
            f"🎮 **{queue_size} people are in the `!nextgame` queue right now.** "
            "Looks like enough interest to try getting a game going!"
        )

        sent_channels = 0
        for channel_id, channel_user_ids in users_by_channel.items():
            if not channel_user_ids:
                continue

            user_pings = " ".join(f"<@{user_id}>" for user_id in sorted(channel_user_ids))
            channel = self.bot.get_channel(channel_id)
            try:
                if channel:
                    await channel.send(f"{user_pings}\n{alert_text}")
                    sent_channels += 1
                else:
                    # Fallback to DM if channel is unavailable.
                    for user_id in channel_user_ids:
                        try:
                            user = await self.bot.fetch_user(user_id)
                            await user.send(alert_text)
                        except Exception as dm_error:
                            logger.error(f"Failed daily queue alert DM to user {user_id}: {dm_error}")
            except Exception as e:
                logger.error(f"Failed sending daily nextgame queue alert to channel {channel_id}: {e}")

        logger.info(
            f"Sent daily nextgame queue alert for {queue_size} queued user(s) "
            f"across {sent_channels} channel(s)"
        )
    
    async def _notify_next_game_waiters(self, trigger_servers: List[Dict]):
        """Notify all waiting users about available games, grouping by channel and PTB preference"""
        if not self.next_game_waiters or not trigger_servers:
            return
        
        # Group waiters by channel and PTB preference
        waiters_by_channel_and_ptb = {}
        for waiter_key, waiter_info in self.next_game_waiters.items():
            user_id, _ = waiter_key
            channel_id = waiter_info['channel_id']
            ptb_only = waiter_info.get('ptb_only', False)
            key = (channel_id, ptb_only)
            if key not in waiters_by_channel_and_ptb:
                waiters_by_channel_and_ptb[key] = []
            waiters_by_channel_and_ptb[key].append((waiter_key, user_id, waiter_info))

        # Notify all waiters, grouped by channel and PTB preference
        waiters_to_remove = set()
        for (channel_id, ptb_only), waiters in waiters_by_channel_and_ptb.items():
            base_servers = trigger_servers
            if ptb_only:
                base_servers = [s for s in trigger_servers if s.get('is_test_branch', False)]
                if not base_servers:
                    continue  # No PTB servers match, skip this group

            # Apply per-waiter skip filtering and collect which users should be pinged
            eligible_waiters = []
            aggregated_servers = []
            aggregated_ids = set()

            for waiter_key, user_id, waiter_info in waiters:
                user_servers = self._filter_servers_for_waiter(base_servers, waiter_info)
                if not user_servers:
                    continue  # Nothing to notify this user about (likely due to --skip)

                eligible_waiters.append((waiter_key, user_id, waiter_info))
                for server in user_servers:
                    server_id = self._server_identity(server)
                    if server_id not in aggregated_ids:
                        aggregated_ids.add(server_id)
                        aggregated_servers.append(server)

            if not eligible_waiters or not aggregated_servers:
                continue  # No one to notify after applying skip filters

            notification_embed = self._build_next_game_notification_embed(aggregated_servers, ptb_only=ptb_only)
            if not notification_embed:
                continue  # No matching servers for this group

            try:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    # Build ping string for eligible users in this channel
                    user_pings = " ".join([f"<@{user_id}>" for _, user_id, _ in eligible_waiters])
                    await channel.send(content=user_pings, embed=notification_embed)

                    # Log and mark for removal
                    for waiter_key, user_id, waiter_info in eligible_waiters:
                        ptb_text = " (PTB only)" if ptb_only else ""
                        logger.info(f"Notified {waiter_info['username']} (ID: {user_id}) about next game{ptb_text}")
                        waiters_to_remove.add(waiter_key)
                else:
                    # Channel not found, try DM for each eligible user
                    for waiter_key, user_id, waiter_info in eligible_waiters:
                        try:
                            user = await self.bot.fetch_user(user_id)
                            await user.send(embed=notification_embed)
                            ptb_text = " (PTB only)" if ptb_only else ""
                            logger.info(f"Notified {waiter_info['username']} (ID: {user_id}) via DM about next game{ptb_text}")
                            waiters_to_remove.add(waiter_key)
                        except Exception as dm_error:
                            logger.error(f"Failed to notify user {user_id} via DM: {dm_error}")
                            waiters_to_remove.add(waiter_key)  # Remove them anyway after failed attempt
            except Exception as e:
                logger.error(f"Error notifying users in channel {channel_id}: {e}")
                # Mark all eligible waiters in this channel for removal on error
                for waiter_key, _, _ in eligible_waiters:
                    waiters_to_remove.add(waiter_key)
        
        # Remove notified users
        for waiter_key in waiters_to_remove:
            if waiter_key in self.next_game_waiters:
                del self.next_game_waiters[waiter_key]
        
        if waiters_to_remove:
            logger.info(f"Removed {len(waiters_to_remove)} next game waitlist entries after notification")
    
    def get_joinable_lobby_ids(self, ptb_only: bool = False) -> List[str]:
        """Return identities of current joinable lobbies (3+ players, not full)."""
        lobby_ids = set()
        for server in self.cached_servers:
            if server.get('status') != 'lobby':
                continue
            players = server.get('players', 0)
            capacity = server.get('map_capacity', 8)
            if players < 3 or players >= capacity:
                continue
            if ptb_only and not server.get('is_test_branch', False):
                continue
            lobby_ids.add(self._server_identity(server))
        return list(lobby_ids)

    def _filter_servers_for_waiter(self, trigger_servers: List[Dict], waiter_info: Dict) -> List[Dict]:
        """
        Apply waiter-specific filters (skip current lobbies) to trigger servers.
        When a skipped lobby leaves lobby state, it is removed from the skip list
        so future new lobbies on that server can notify the user.
        """
        skip_ids = set(waiter_info.get('skip_lobbies', []))
        filtered = []

        for server in trigger_servers:
            server_id = self._server_identity(server)
            status = server.get('status')

            if status == 'lobby' and server_id in skip_ids:
                # Skip lobbies that were active when the user opted in with --skip
                continue

            filtered.append(server)

            # If a previously skipped server left lobby, allow future notifications
            if server_id in skip_ids and status != 'lobby':
                skip_ids.discard(server_id)

        # Persist any updates to the skip list
        waiter_info['skip_lobbies'] = list(skip_ids)
        return filtered

    def resolve_server_names(self, server_ids: List[str], ptb_only: bool = False) -> List[str]:
        """Best-effort resolve server identities to human-friendly names."""
        id_set = set(server_ids or [])
        if not id_set:
            return []

        names = []
        for server in self.cached_servers:
            if ptb_only and not server.get('is_test_branch', False):
                continue

            server_id = self._server_identity(server)
            if server_id in id_set:
                names.append(self.sanitize_server_name_for_display(server.get('name', 'Unknown')))

        # Fallback for any unmatched ids
        if len(names) < len(id_set):
            remaining = len(id_set) - len(names)
            names.append(f"{remaining} unnamed/unknown lobby(s)")

        return names

    def _next_game_waiter_key(self, user_id: int, ptb_only: bool) -> Tuple[int, bool]:
        """Build the waitlist key for a user and queue mode."""
        return (user_id, ptb_only)

    def get_next_game_waiter(self, user_id: int, ptb_only: bool = False) -> Optional[Dict]:
        """Return waitlist info for a specific queue mode."""
        return self.next_game_waiters.get(self._next_game_waiter_key(user_id, ptb_only))

    def is_user_waiting_for_next_game(self, user_id: int, ptb_only: Optional[bool] = None) -> bool:
        """
        Check whether a user is already queued.
        If ptb_only is None, checks any queue mode for that user.
        """
        if ptb_only is None:
            return any(waiter_user_id == user_id for waiter_user_id, _ in self.next_game_waiters.keys())
        return self._next_game_waiter_key(user_id, ptb_only) in self.next_game_waiters

    def add_next_game_waiter(self, user_id: int, channel_id: int, username: str, ptb_only: bool = False, skip_lobbies: Optional[List[str]] = None):
        """Add a user to the next game waitlist"""
        waiter_key = self._next_game_waiter_key(user_id, ptb_only)
        self.next_game_waiters[waiter_key] = {
            'channel_id': channel_id,
            'timestamp': datetime.now(timezone.utc),
            'username': username,
            'ptb_only': ptb_only,
            'skip_lobbies': skip_lobbies or []
        }
        ptb_text = " (PTB only)" if ptb_only else ""
        skip_text = " with skip" if skip_lobbies else ""
        logger.info(f"Added {username} (ID: {user_id}) to next game waitlist{ptb_text}{skip_text}")
    
    def remove_next_game_waiter(self, user_id: int, ptb_only: Optional[bool] = None) -> bool:
        """
        Remove a user from the next game waitlist.
        If ptb_only is None, remove user from all queue modes.
        Returns True if at least one waitlist entry was removed.
        """
        if ptb_only is not None:
            waiter_key = self._next_game_waiter_key(user_id, ptb_only)
            if waiter_key in self.next_game_waiters:
                username = self.next_game_waiters[waiter_key]['username']
                del self.next_game_waiters[waiter_key]
                ptb_text = " (PTB only)" if ptb_only else ""
                logger.info(f"Removed {username} (ID: {user_id}) from next game waitlist{ptb_text}")
                return True
            return False

        keys_to_remove = [key for key in self.next_game_waiters if key[0] == user_id]
        if not keys_to_remove:
            return False

        username = self.next_game_waiters[keys_to_remove[0]]['username']
        for key in keys_to_remove:
            del self.next_game_waiters[key]

        logger.info(f"Removed {username} (ID: {user_id}) from {len(keys_to_remove)} next game waitlist queue(s)")
        return True
    
    def get_next_game_waiters_count(self) -> int:
        """Get the number of unique users waiting for next game notifications."""
        return len({user_id for user_id, _ in self.next_game_waiters.keys()})
    
    def find_matching_servers_for_notification(self, ptb_only: bool = False) -> List[Dict]:
        """
        Find servers that match the notification criteria:
        - Lobby servers with 3+ players but less than max capacity
        - Servers in debrief status
        - If ptb_only=True, only return PTB (test branch) servers
        Returns list of matching servers.
        """
        trigger_servers = []
        
        # Check for joinable lobby servers with 3+ players
        for server in self.cached_servers:
            if server.get('status') == 'lobby':
                players = server.get('players', 0)
                capacity = server.get('map_capacity', 8)
                # Only notify for lobbies with 3+ players that still have space
                if players >= 3 and players < capacity:
                    # Filter by PTB if requested
                    if not ptb_only or server.get('is_test_branch', False):
                        trigger_servers.append(server)
        
        # Check for servers in debrief
        for server in self.cached_servers:
            if server.get('status') == 'debrief':
                # Filter by PTB if requested
                if not ptb_only or server.get('is_test_branch', False):
                    if server not in trigger_servers:
                        trigger_servers.append(server)
        
        # Also check recent debrief transitions
        for server_id, server in self.recent_debrief_transitions.items():
            # Filter by PTB if requested
            if not ptb_only or server.get('is_test_branch', False):
                if server not in trigger_servers:
                    trigger_servers.append(server)
        
        return trigger_servers

    def _build_next_game_notification_embed(self, trigger_servers: List[Dict], ptb_only: bool = False) -> Optional[discord.Embed]:
        """Build an embed for next game alerts."""
        if not trigger_servers:
            return None

        debrief_servers = [s for s in trigger_servers if s.get('status') == 'debrief']
        active_servers = [s for s in trigger_servers if s.get('status') != 'debrief']
        if not debrief_servers and not active_servers:
            return None

        title = "🧪 PTB Game Ready!" if ptb_only else "🚀 Game Ready!"
        description = (
            "A PTB game is ready to join or just entered debrief."
            if ptb_only else
            "A game is ready to join or just entered debrief."
        )
        embed = discord.Embed(
            title=title,
            description=description,
            color=Config.EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        if debrief_servers:
            debrief_list = []
            for server in debrief_servers[:5]:
                name = self.sanitize_server_name_for_display(server.get('name', 'Unknown'))[:40]
                debrief_list.append(f"• {name}")
            embed.add_field(
                name=f"🎮 {len(debrief_servers)} game(s) just finished (in debrief)",
                value="\n".join(debrief_list),
                inline=False
            )

        if active_servers:
            active_list = []
            for server in active_servers[:5]:
                name = self.sanitize_server_name_for_display(server.get('name', 'Unknown'))[:40]
                players = server.get('players', 0)
                capacity = server.get('map_capacity', 8)
                available_slots = capacity - players
                active_list.append(f"• {name} - {players}/{capacity} players ({available_slots} slot(s) available)")
            embed.add_field(
                name=f"🚀 {len(active_servers)} lobby(ies) filling up (3+ players, joinable)",
                value="\n".join(active_list),
                inline=False
            )

        embed.set_footer(text="Use !listservers or !openlobbies to see all servers")
        return embed
    
    async def notify_single_user_immediately(self, user_id: int, trigger_servers: List[Dict], ptb_only: bool = False) -> bool:
        """
        Notify a single user immediately about available games for a specific queue mode.
        Returns True if notification was sent, False otherwise.
        """
        waiter_key = self._next_game_waiter_key(user_id, ptb_only)
        if waiter_key not in self.next_game_waiters or not trigger_servers:
            return False
        
        waiter_info = self.next_game_waiters[waiter_key]
        channel_id = waiter_info['channel_id']
        ptb_only = waiter_info.get('ptb_only', False)
        
        # Filter servers by PTB preference if needed
        if ptb_only:
            trigger_servers = [s for s in trigger_servers if s.get('is_test_branch', False)]
            if not trigger_servers:
                return False  # No PTB servers match

        # Respect per-waiter skip list (current lobbies)
        trigger_servers = self._filter_servers_for_waiter(trigger_servers, waiter_info)
        if not trigger_servers:
            return False
        
        notification_embed = self._build_next_game_notification_embed(trigger_servers, ptb_only=ptb_only)
        if not notification_embed:
            return False
        
        try:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(content=f"<@{user_id}>", embed=notification_embed)
                logger.info(f"Immediately notified {waiter_info['username']} (ID: {user_id}) about available games")
                # Remove user from waitlist after immediate notification
                del self.next_game_waiters[waiter_key]
                # Clear debrief transitions if this was the only waiter
                if not self.next_game_waiters:
                    self.recent_debrief_transitions.clear()
                return True
            else:
                # Channel not found, try DM
                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(embed=notification_embed)
                    logger.info(f"Immediately notified {waiter_info['username']} (ID: {user_id}) via DM about available games")
                    del self.next_game_waiters[waiter_key]
                    if not self.next_game_waiters:
                        self.recent_debrief_transitions.clear()
                    return True
                except Exception as dm_error:
                    logger.error(f"Failed to notify user {user_id} via DM: {dm_error}")
                    return False
        except Exception as e:
            logger.error(f"Error notifying user {user_id}: {e}")
            return False 
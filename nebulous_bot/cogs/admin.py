"""Admin and bot-info commands: !restartmonitor, !debugmonitor, !status,
!version, !commandlogs.

Command bodies are moved verbatim from runbot.py. get_deployment_time
lives here because only !status uses it; the bot-start fallback timestamp
is ``bot.deployment_time``, set by on_ready.
"""
import discord
from discord.ext import commands
import logging
import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from nebulous_bot.config import Config

logger = logging.getLogger('nebulous_bot')


class AdminCog(commands.Cog, name='Admin'):
    """Monitoring control and bot status/version commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_deployment_time(self) -> Optional[datetime]:
        """Get deployment time from environment variable or tracked bot start time"""
        # First, check for environment variable (set during deployment)
        deployment_time_str = os.getenv('DEPLOYMENT_TIME')
        if deployment_time_str:
            try:
                # Try parsing ISO format timestamp
                return datetime.fromisoformat(deployment_time_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                try:
                    # Try parsing Unix timestamp
                    return datetime.fromtimestamp(float(deployment_time_str), tz=timezone.utc)
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse DEPLOYMENT_TIME: {deployment_time_str}")

        # Fall back to tracked bot start time
        return self.bot.deployment_time

    @commands.command(name='restartmonitor', aliases=['restart'])
    @commands.has_permissions(administrator=True)
    async def restart_monitoring(self, ctx):
        """Restart the monitoring loop (admin only)"""
        server_monitor = self.bot.server_monitor
        if not server_monitor:
            await ctx.send("❌ Server monitoring not initialized yet.")
            return

        status_msg = await ctx.send("🔄 Restarting monitoring loop...")

        try:
            # Stop existing monitoring if running
            await server_monitor.stop_monitoring()
            await asyncio.sleep(1)

            # Start monitoring again
            await server_monitor.start_monitoring()

            # Verify it started
            task_running = server_monitor.monitoring_task and not server_monitor.monitoring_task.done()

            embed = discord.Embed(
                title="✅ Monitoring Restarted",
                description=f"The monitoring loop has been restarted successfully.\nTask running: {task_running}",
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )
            await status_msg.edit(content="", embed=embed)
            logger.info(f"Monitoring loop restarted by {ctx.author}. Task running: {task_running}")
        except Exception as e:
            logger.error(f"Error restarting monitoring: {e}", exc_info=True)
            await status_msg.edit(content=f"❌ Failed to restart monitoring: {str(e)}")

    @commands.command(name='debugmonitor')
    @commands.has_permissions(administrator=True)
    async def debug_monitor(self, ctx):
        """Show detailed monitoring loop debug info (admin only)"""
        server_monitor = self.bot.server_monitor
        if not server_monitor:
            await ctx.send("❌ Server monitoring not initialized yet.")
            return

        info = []
        info.append(f"**Server Monitor Initialized:** {'✅ Yes' if server_monitor else '❌ No'}")
        info.append(f"**Formatter Set:** {'✅ Yes' if server_monitor.formatter else '❌ No'}")
        info.append(f"**Monitoring Task:** {server_monitor.monitoring_task}")

        if server_monitor.monitoring_task:
            info.append(f"**Task Done:** {server_monitor.monitoring_task.done()}")
            if server_monitor.monitoring_task.done():
                try:
                    exc = server_monitor.monitoring_task.exception()
                    info.append(f"**Task Exception:** {exc}")
                except:
                    info.append("**Task Exception:** Unable to retrieve")
            else:
                info.append("**Task Status:** Running")

        info.append(f"**Cached Servers:** {len(server_monitor.cached_servers)}")
        info.append(f"**Last Update:** {server_monitor.last_update}")
        info.append(f"**Config Update Interval:** {Config.UPDATE_INTERVAL}s")
        info.append(f"**Guilds Connected:** {len(self.bot.guilds)}")

        await ctx.send("**Monitoring Loop Debug Info:**\n" + "\n".join(info))

    @commands.command(name='status', aliases=['info'])
    async def show_status(self, ctx):
        """Show bot status and information"""
        server_monitor = self.bot.server_monitor
        embed = discord.Embed(
            title="🤖 Nebulous Server Bot Status",
            color=Config.EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        if server_monitor:
            last_update = server_monitor.last_update
            server_count = len(server_monitor.cached_servers)

            # Check if monitoring task is actually running
            task_status = "❌ Not Running"
            if server_monitor.monitoring_task:
                if server_monitor.monitoring_task.done():
                    task_status = "❌ Stopped (check logs)"
                    try:
                        # Check if task had an exception
                        exc = server_monitor.monitoring_task.exception()
                        if exc:
                            task_status = f"❌ Failed: {str(exc)[:50]}"
                    except:
                        pass
                else:
                    task_status = "✅ Running"

            embed.add_field(
                name="📊 Server Monitoring",
                value=f"**Task Status:** {task_status}\n**Servers Tracked:** {server_count}\n**Update Interval:** {Config.UPDATE_INTERVAL}s",
                inline=True
            )

            if last_update:
                embed.add_field(
                    name="🕒 Last Update",
                    value=f"<t:{int(last_update.timestamp())}:R>",
                    inline=True
                )
        else:
            embed.add_field(
                name="📊 Server Monitoring",
                value="**Active:** ❌\n**Status:** Initializing...",
                inline=True
            )

        # Add deployment time
        deployment_dt = self.get_deployment_time()
        if deployment_dt:
            embed.add_field(
                name="🚀 Last Deployment",
                value=f"<t:{int(deployment_dt.timestamp())}:R>",
                inline=True
            )

        embed.add_field(
            name="🎮 Game",
            value=f"**{Config.GAME_NAME}**\nApp ID: {Config.NEBULOUS_APP_ID}",
            inline=True
        )

        embed.add_field(
            name="🔥 Popular Commands",
            value=(
                "`!help` - Full command menu\n"
                "`!listservers` - List all servers\n"
                "`!openlobbies` - Show available servers\n"
                "`!stats` - View game statistics\n"
                "`!mapstats` - View map statistics\n"
                "`!serverstats` - View server statistics\n"
                "`!graph` - Display graphs of data over the last week\n"
                "`!nextgame` - Get notified when a game is ready (options: `ptb`, `modded`, `newplayer`, `lobby`, `--skip`)\n"
                "`!formation` - Optimize fleet formation file\n"
                "`!refresh` - Force update\n"
                "`!version` - Show version and changelog"
            ),
            inline=False
        )

        embed.set_footer(text="Bot running smoothly! • Created by Davaned")
        await ctx.send(embed=embed)

    @commands.command(name='version', aliases=['v', 'changelog'])
    async def show_version(self, ctx):
        """Show bot version and changelog"""
        embed = discord.Embed(
            title=f"🤖 Nebulous Server Bot v{Config.VERSION}",
            description="Current version and recent changes",
            color=Config.EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )

        # Show current version
        embed.add_field(
            name="📌 Current Version",
            value=f"**v{Config.VERSION}**",
            inline=False
        )

        # Show concise recent changelog and keep within Discord field limits.
        lines = []
        for entry in Config.CHANGELOG[:3]:
            version = entry.get('version', 'Unknown')
            date = entry.get('date', 'Unknown')
            changes = entry.get('changes', [])

            lines.append(f"**v{version}** ({date})")
            for change in changes[:2]:
                lines.append(f"• {change}")
            if len(changes) > 2:
                lines.append(f"• +{len(changes) - 2} more")
            lines.append("")

        changelog_text = "\n".join(lines).strip() or "No changelog available"
        if len(changelog_text) > 1000:
            changelog_text = changelog_text[:997].rstrip() + "..."

        embed.add_field(
            name="📋 Recent Changes",
            value=changelog_text,
            inline=False
        )

        embed.set_footer(text="Use !help for the command menu • !status for bot information")
        await ctx.send(embed=embed)

    @commands.command(name='commandlogs', aliases=['cmdlogs', 'logs'], hidden=True)
    @commands.is_owner()
    async def show_command_logs(self, ctx, limit: int = 20, command_filter: str = None):
        """
        View command usage logs (bot owner only — exposes cross-guild usage data)

        Usage: !commandlogs [limit] [command_name]
        Examples: !commandlogs 10, !commandlogs 50 stats
        """
        from nebulous_bot.models import CommandLog
        from django.db.models import Count
        from asgiref.sync import sync_to_async

        # Limit to prevent abuse
        limit = min(limit, 100)

        @sync_to_async
        def get_command_logs():
            logs = CommandLog.objects.all().order_by('-timestamp')

            # Filter by command if specified
            if command_filter:
                logs = logs.filter(command_name__icontains=command_filter)

            # Get recent logs
            recent_logs = list(logs[:limit])

            # Get summary stats
            total_count = CommandLog.objects.count()
            success_count = CommandLog.objects.filter(success=True).count()
            error_count = CommandLog.objects.filter(success=False).count()

            # Get top commands
            top_commands = list(
                CommandLog.objects.values('command_name')
                .annotate(count=Count('id'))
                .order_by('-count')[:5]
            )

            # Get context breakdown (guild vs DM)
            guild_commands = CommandLog.objects.filter(context_type='guild').count()
            dm_commands = CommandLog.objects.filter(context_type='dm').count()
            thread_commands = CommandLog.objects.filter(context_type='thread').count()

            # Get unique users by context
            guild_users = CommandLog.objects.filter(context_type='guild').values('user_id').distinct().count()
            dm_users = CommandLog.objects.filter(context_type='dm').values('user_id').distinct().count()
            thread_users = CommandLog.objects.filter(context_type='thread').values('user_id').distinct().count()

            # Total unique users who have used DMs
            total_dm_users = CommandLog.objects.filter(context_type='dm').values('user_id').distinct().count()

            # Total unique users overall
            total_unique_users = CommandLog.objects.values('user_id').distinct().count()

            return recent_logs, total_count, success_count, error_count, top_commands, \
                   guild_commands, dm_commands, thread_commands, \
                   guild_users, dm_users, thread_users, total_dm_users, total_unique_users

        try:
            logs, total, success, errors, top_commands, \
            guild_commands, dm_commands, thread_commands, \
            guild_users, dm_users, thread_users, total_dm_users, total_unique_users = await get_command_logs()

            if not logs:
                embed = discord.Embed(
                    title="📋 Command Logs",
                    description="No command logs found yet.",
                    color=Config.EMBED_COLOR_NO_SERVERS
                )
                await ctx.send(embed=embed)
                return

            embed = discord.Embed(
                title=f"📋 Command Logs (Last {len(logs)})",
                color=Config.EMBED_COLOR,
                timestamp=datetime.now(timezone.utc)
            )

            # Summary statistics
            embed.add_field(
                name="📊 Summary",
                value=(
                    f"**Total Commands:** {total:,}\n"
                    f"**Successful:** {success:,} ({success*100//total if total > 0 else 0}%)\n"
                    f"**Errors:** {errors:,} ({errors*100//total if total > 0 else 0}%)"
                ),
                inline=True
            )

            # Context breakdown (Guild vs DM)
            context_text = (
                f"**Servers:** {guild_commands:,} ({guild_commands*100//total if total > 0 else 0}%)\n"
                f"**DMs:** {dm_commands:,} ({dm_commands*100//total if total > 0 else 0}%)\n"
            )
            if thread_commands > 0:
                context_text += f"**Threads:** {thread_commands:,} ({thread_commands*100//total if total > 0 else 0}%)"

            embed.add_field(
                name="📍 Usage by Location",
                value=context_text,
                inline=True
            )

            # User breakdown
            user_text = (
                f"**Server Users:** {guild_users:,}\n"
                f"**DM Users:** {dm_users:,}\n"
                f"**Total Unique:** {total_unique_users:,}"
            )
            if thread_users > 0:
                user_text = user_text.replace("**Total Unique:**", f"**Thread Users:** {thread_users:,}\n**Total Unique:**")

            embed.add_field(
                name="👥 Unique Users",
                value=user_text,
                inline=True
            )

            # Top commands
            if top_commands:
                top_text = "\n".join([
                    f"**{i+1}.** `{cmd['command_name']}`: {cmd['count']}"
                    for i, cmd in enumerate(top_commands)
                ])
                embed.add_field(
                    name="🔥 Top Commands",
                    value=top_text,
                    inline=False
                )

            # Recent logs (show first 10 in detail)
            log_text = ""
            for i, log in enumerate(logs[:10], 1):
                status = "✅" if log.success else f"❌ {log.error_type}"
                location = log.context_type
                if log.guild_name:
                    location = f"{log.guild_name[:20]}"
                elif log.guild_id:
                    location = f"Guild {log.guild_id}"

                time_str = log.timestamp.strftime("%m/%d %H:%M")
                latency = f"{log.latency_ms}ms" if log.latency_ms else "N/A"

                log_text += f"**{i}.** `{log.command_name}` by {log.user_name[:15]}\n"
                log_text += f"   {status} • {location} • {time_str} • {latency}\n"

            if len(logs) > 10:
                log_text += f"\n*... and {len(logs) - 10} more*"

            embed.add_field(
                name="📝 Recent Commands",
                value=log_text,
                inline=False
            )

            if command_filter:
                embed.set_footer(text=f"Filtered by: {command_filter}")

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error fetching command logs: {e}", exc_info=True)
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to fetch command logs: {str(e)}",
                color=Config.EMBED_COLOR_NO_SERVERS
            )
            await ctx.send(embed=embed)

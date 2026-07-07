"""Per-guild setup commands.

An admin in a server runs these to tell the bot where to post the
live status embed and (optionally) where to send threshold pings.
Writes go to the GuildConfig table and override the env-var
bootstrap config on guild_id collision. Without these, a guild
added via Discord's Add-to-Server flow would be visible to the
bot but would never receive the live status message.
"""
import discord
from discord.ext import commands

from nebulous_bot.config import Config


async def _upsert_guild_config(guild_id: int, **fields):
    """Create-or-update the GuildConfig row for a guild, off-loop."""
    from asgiref.sync import sync_to_async
    from nebulous_bot.models import GuildConfig

    @sync_to_async
    def _do():
        obj, _created = GuildConfig.objects.update_or_create(
            guild_id=guild_id,
            defaults=fields,
        )
        return obj
    return await _do()


class SetupCog(commands.Cog, name='Setup'):
    """Per-guild configuration commands (status channel, notifications)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='setstatuschannel', aliases=['setstatus'])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def set_status_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel where the bot posts the live server status (admin only).

        With no argument, uses the channel where the command is run.
        """
        target = channel or ctx.channel
        await _upsert_guild_config(ctx.guild.id, status_channel_id=target.id)
        embed = discord.Embed(
            title="✅ Status channel set",
            description=f"I'll post live server status updates in {target.mention}.",
            color=Config.EMBED_COLOR,
        )
        embed.set_footer(text="The first status message appears within ~30 seconds.")
        await ctx.send(embed=embed)

    @commands.command(name='setnotificationchannel', aliases=['setnotifchannel'])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def set_notification_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel for player-threshold notifications (admin only).

        Optional. Without this, no threshold pings are sent for the guild.
        """
        target = channel or ctx.channel
        await _upsert_guild_config(ctx.guild.id, notification_channel_id=target.id)
        embed = discord.Embed(
            title="✅ Notification channel set",
            description=f"Threshold pings will go to {target.mention}.",
            color=Config.EMBED_COLOR,
        )
        embed.set_footer(text="Use !setnotificationrole to choose which role gets pinged.")
        await ctx.send(embed=embed)

    @commands.command(name='setnotificationrole', aliases=['setnotifrole'])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def set_notification_role(self, ctx, role: discord.Role):
        """Set the role to ping for threshold notifications (admin only)."""
        await _upsert_guild_config(ctx.guild.id, notification_role_id=role.id)
        embed = discord.Embed(
            title="✅ Notification role set",
            description=f"I'll ping {role.mention} for threshold notifications.",
            color=Config.EMBED_COLOR,
        )
        await ctx.send(embed=embed)

    @commands.command(name='removestatus', aliases=['unsetstatus'])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def remove_status(self, ctx):
        """Stop posting the live server status in this guild (admin only)."""
        await _upsert_guild_config(ctx.guild.id, status_channel_id=None)
        embed = discord.Embed(
            title="🛑 Status posting disabled",
            description="I'll stop posting live status updates here. Run `!setstatuschannel` again to re-enable.",
            color=Config.EMBED_COLOR_NO_SERVERS,
        )
        await ctx.send(embed=embed)

    @commands.command(name='showsetup', aliases=['mysetup', 'guildconfig'])
    @commands.guild_only()
    async def show_setup(self, ctx):
        """Show the bot's configuration for this guild."""
        from asgiref.sync import sync_to_async

        @sync_to_async
        def _resolve():
            # Returns (status_id, notif_channel_id, notif_role_id, source)
            # where source ∈ {'db', 'env', 'unset'}.
            from nebulous_bot.models import GuildConfig
            try:
                row = GuildConfig.objects.get(guild_id=ctx.guild.id)
                return (
                    row.status_channel_id,
                    row.notification_channel_id,
                    row.notification_role_id,
                    'db',
                )
            except GuildConfig.DoesNotExist:
                pass
            for entry in Config.SERVER_CONFIGS:
                if entry['guild_id'] == ctx.guild.id:
                    return (
                        entry.get('status_channel_id'),
                        entry.get('notification_channel_id'),
                        entry.get('notification_role_id'),
                        'env',
                    )
            return (None, None, None, 'unset')

        status_id, notif_chan_id, notif_role_id, source = await _resolve()

        def _channel_str(cid):
            if cid is None:
                return "*(not set)*"
            ch = ctx.guild.get_channel(cid)
            return ch.mention if ch else f"`{cid}` *(not found)*"

        def _role_str(rid):
            if rid is None:
                return "*(not set)*"
            role = ctx.guild.get_role(rid)
            return role.mention if role else f"`{rid}` *(not found)*"

        source_text = {
            'db': "set by an admin command",
            'env': "loaded from the bot's bootstrap config",
            'unset': "not configured — run `!setstatuschannel` to start",
        }[source]

        embed = discord.Embed(
            title=f"⚙️ Setup for {ctx.guild.name}",
            description=f"_{source_text}_",
            color=Config.EMBED_COLOR,
        )
        embed.add_field(name="Live status channel", value=_channel_str(status_id), inline=False)
        embed.add_field(name="Threshold notification channel", value=_channel_str(notif_chan_id), inline=False)
        embed.add_field(name="Threshold ping role", value=_role_str(notif_role_id), inline=False)
        embed.set_footer(text="Admins: !setstatuschannel · !setnotificationchannel · !setnotificationrole · !removestatus")
        await ctx.send(embed=embed)

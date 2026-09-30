import time
from typing import Optional

from asgiref.sync import sync_to_async
from discord.ext import commands

from nebulous_bot.config import Config
from nebulous_bot.models import CommandLog

def _detect_context_type(ctx: commands.Context) -> str:
    """Return a simple label for where the command was invoked."""
    if ctx.guild is None:
        return "dm"
    channel = getattr(ctx, "channel", None)
    if channel and getattr(channel, "type", None):
        if channel.type.name.endswith("thread"):
            return "thread"
    return "guild"


class CommandMetricsLogger:
    """Attach hooks to a Discord bot to persist command usage metrics."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def register(self) -> None:
        """Register before/after hooks and error listener."""
        self.bot.before_invoke(self._track_start)
        self.bot.after_invoke(self._log_success)
        self.bot.add_listener(self._log_error, "on_command_error")

    async def _track_start(self, ctx: commands.Context) -> None:
        ctx._command_start_time = time.perf_counter()  # type: ignore[attr-defined]

    async def _log_success(self, ctx: commands.Context) -> None:
        if getattr(ctx, "command_failed", False):
            return
        await self._create_log(ctx, success=True, error_type=None)

    async def _log_error(self, ctx: commands.Context, error: Exception) -> None:
        # Let other handlers run; we only care about logging
        if isinstance(error, commands.CommandNotFound):
            return
        await self._create_log(ctx, success=False, error_type=error.__class__.__name__)

    async def _create_log(
        self,
        ctx: commands.Context,
        success: bool,
        error_type: Optional[str],
    ) -> None:
        """Persist a CommandLog entry via Django's ORM in a thread."""
        if not getattr(ctx, "command", None):
            return
        if getattr(ctx, "_command_log_written", False):
            return
        ctx._command_log_written = True  # type: ignore[attr-defined]

        start_time = getattr(ctx, "_command_start_time", None)
        duration_ms = None
        if start_time:
            duration_ms = int((time.perf_counter() - start_time) * 1000)

        guild = ctx.guild
        channel = getattr(ctx, "channel", None)
        message = getattr(ctx, "message", None)

        command_name = ctx.command.qualified_name or ctx.command.name
        invocation_type = "slash" if getattr(ctx, "interaction", None) else "prefix"
        full_command = f"{invocation_type}:{command_name}"

        context_type = _detect_context_type(ctx)

        await self._save_log(
            timestamp=None,  # auto_now_add handles this
            command_name=command_name,
            full_command=full_command,
            user_id=getattr(ctx.author, "id", None),
            user_name=str(getattr(ctx, "author", "")),
            guild_id=guild.id if guild else None,
            guild_name=guild.name if guild and getattr(guild, "name", None) else "",
            channel_id=channel.id if channel and getattr(channel, "id", None) else None,
            channel_name=getattr(channel, "name", "") if channel else "",
            context_type=context_type,
            message_id=message.id if message and getattr(message, "id", None) else None,
            # The column remains for schema compatibility and expiry of
            # legacy rows, but new invocations never store message content.
            arguments="",
            success=success,
            error_type=error_type or "",
            latency_ms=duration_ms,
            bot_version=getattr(Config, "VERSION", ""),
        )

    @staticmethod
    @sync_to_async
    def _save_log(**kwargs) -> None:
        CommandLog.objects.create(**kwargs)


def setup_command_metrics(bot: commands.Bot) -> CommandMetricsLogger:
    """
    Convenience helper to register metrics logging against a bot instance.
    
    Returns the logger instance in case the caller needs a reference.
    """
    logger = CommandMetricsLogger(bot)
    logger.register()
    return logger


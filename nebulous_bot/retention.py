"""30-day retention for stored message content (CommandLog.arguments).

PRIVACY.md commits to keeping message content for at most 30 days; this
module enforces that by blanking the ``arguments`` field on old rows.
The row itself (command name, ids, latency) is kept for statistics —
only the message-content field is cleared.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from asgiref.sync import sync_to_async

logger = logging.getLogger("nebulous_bot")

RETENTION_DAYS = 30
PURGE_INTERVAL_SECONDS = 24 * 60 * 60


def retention_cutoff(now: datetime, days: int = RETENTION_DAYS) -> datetime:
    """Timestamp before which stored command arguments must be blanked."""
    return now - timedelta(days=days)


def purge_expired_command_arguments(now: Optional[datetime] = None) -> int:
    """Blank CommandLog.arguments on rows older than RETENTION_DAYS.

    Returns the number of rows updated. Sync ORM code — call via
    sync_to_async from the event loop.
    """
    from django.utils import timezone

    from nebulous_bot.models import CommandLog

    if now is None:
        now = timezone.now()
    cutoff = retention_cutoff(now)
    return CommandLog.objects.filter(timestamp__lt=cutoff).exclude(arguments="").update(arguments="")


async def run_retention_loop() -> None:
    """Purge once at startup, then daily. Started from on_ready."""
    while True:
        try:
            updated = await sync_to_async(purge_expired_command_arguments)()
            if updated:
                logger.info(f"Retention purge blanked arguments on {updated} command log rows")
        except Exception as e:
            logger.error(f"Retention purge failed: {e}")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)

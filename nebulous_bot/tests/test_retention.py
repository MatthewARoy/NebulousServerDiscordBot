"""Pure-logic tests for the message-content retention policy."""

from datetime import datetime, timedelta, timezone

from nebulous_bot import retention


def test_cutoff_is_thirty_days_before_now():
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert retention.retention_cutoff(now) == now - timedelta(days=30)


def test_cutoff_honors_custom_days():
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert retention.retention_cutoff(now, days=7) == now - timedelta(days=7)


def test_policy_constants_match_privacy_policy():
    # PRIVACY.md promises message content is kept for at most 30 days,
    # checked at least daily. Changing these means changing the policy.
    assert retention.RETENTION_DAYS == 30
    assert retention.PURGE_INTERVAL_SECONDS <= 24 * 60 * 60

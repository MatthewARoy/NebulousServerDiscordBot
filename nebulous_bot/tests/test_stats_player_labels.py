"""/stats must say which population each number covers, and survive missing Steam data."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from nebulous_bot.cogs.stats import (
    format_current_status,
    format_player_activity,
    format_steam_note,
)


def snapshot(steam=None):
    return SimpleNamespace(
        total_players=5, steam_concurrent=steam, total_servers=1, games_in_progress=0
    )


def test_activity_labels_server_figures_as_servers():
    text = format_player_activity(4.25, 12, 7.5)

    assert text == (
        "**Avg on Servers:** 4.2\n"
        "**Peak on Servers:** 12\n"
        "**Avg Players/Game:** 7.5"
    )
    assert "Online" not in text


def test_activity_adds_steam_lines_once_there_is_data():
    text = format_player_activity(4.0, 12, 7.5, 43.26, 80)

    assert "**Avg on Steam:** 43.3" in text
    assert "**Peak on Steam:** 80" in text


def test_activity_shows_a_real_zero_from_steam():
    assert "**Peak on Steam:** 0" in format_player_activity(4.0, 12, 7.5, 0.0, 0)


def test_status_shows_both_populations():
    text = format_current_status(snapshot(steam=42))

    assert "**Players on Servers:** 5" in text
    assert "**Players on Steam:** 42" in text
    assert "Online" not in text


def test_status_keeps_a_zero_steam_count():
    assert "**Players on Steam:** 0" in format_current_status(snapshot(steam=0))


def test_status_leaves_out_an_unknown_steam_count():
    text = format_current_status(snapshot(steam=None))

    assert "Steam" not in text
    assert "**Players on Servers:** 5" in text


SINCE = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def test_no_steam_data_means_no_note():
    assert format_steam_note(None, None, timezone.utc) is None


def test_all_time_note_says_when_steam_tracking_began():
    note = format_steam_note(SINCE, None, timezone.utc)

    assert note == "Steam counts everyone running the game, tracked since Nov 05, 2026"


def test_window_longer_than_steam_history_says_when_tracking_began():
    assert "tracked since" in format_steam_note(SINCE, SINCE - timedelta(days=7), timezone.utc)


def test_fully_covered_window_omits_the_date():
    note = format_steam_note(SINCE, SINCE - timedelta(minutes=5), timezone.utc)

    assert note == "Steam counts everyone running the game"

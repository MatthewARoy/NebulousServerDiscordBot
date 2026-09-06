"""Slash-command contracts for statistics and next-game commands."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from discord.ext import commands
from discord.ext.commands.view import StringView

from nebulous_bot.cogs.nextgame import NextGameCog
from nebulous_bot.cogs.stats import StatsCog


@pytest.mark.parametrize(
    ("command", "name", "aliases", "parameter_names"),
    [
        (StatsCog.show_statistics, "stats", {"statistics"}, {"timeframe"}),
        (StatsCog.show_map_statistics, "mapstats", {"maps"}, {"limit"}),
        (StatsCog.show_server_statistics, "serverstats", {"serverinfo"}, {"limit"}),
        (StatsCog.show_graph, "graph", set(), {"metric"}),
        (NextGameCog.next_game_notify, "nextgame", {"notify", "notifyme", "ng"}, {"filters"}),
        (NextGameCog.cancel_next_game_notify, "cancelnextgame", {"nextgamecancel"}, set()),
    ],
)
def test_public_commands_have_hybrid_slash_contracts(command, name, aliases, parameter_names):
    assert isinstance(command, commands.HybridCommand)
    assert command.name == name
    assert set(command.aliases) == aliases
    assert command.app_command is not None
    assert command.app_command.description
    assert {parameter.display_name for parameter in command.app_command.parameters} == parameter_names


@pytest.mark.parametrize(
    ("command", "rate", "period", "bucket_type"),
    [
        (StatsCog.show_graph, 1, 15.0, commands.BucketType.channel),
        (NextGameCog.next_game_notify, 2, 30.0, commands.BucketType.user),
    ],
)
def test_hybrid_conversion_preserves_cooldowns(command, rate, period, bucket_type):
    cooldown = command._buckets._cooldown
    assert cooldown is not None
    assert cooldown.rate == rate
    assert cooldown.per == period
    assert command._buckets.type is bucket_type


def _method_node(path: Path, method_name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name:
            return node
    raise AssertionError(f"Could not find {method_name} in {path}")


def _awaited_call_line(method: ast.AsyncFunctionDef, call_name: str) -> int:
    for node in ast.walk(method):
        if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
            continue
        function = node.value.func
        if isinstance(function, ast.Name) and function.id == call_name:
            return node.lineno
        if isinstance(function, ast.Attribute) and function.attr == call_name:
            return node.lineno
    raise AssertionError(f"Could not find awaited call to {call_name}")


def _awaited_call_lines(method: ast.AsyncFunctionDef, call_name: str) -> list[int]:
    lines = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
            continue
        function = node.value.func
        if isinstance(function, ast.Name) and function.id == call_name:
            lines.append(node.lineno)
        elif isinstance(function, ast.Attribute) and function.attr == call_name:
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    ("path", "method_name", "slow_call"),
    [
        (Path("nebulous_bot/cogs/stats.py"), "show_statistics", "get_statistics"),
        (Path("nebulous_bot/cogs/stats.py"), "show_map_statistics", "get_map_stats"),
        (Path("nebulous_bot/cogs/stats.py"), "show_server_statistics", "get_server_stats"),
        (Path("nebulous_bot/cogs/stats.py"), "show_graph", "get_graph_data"),
        (Path("nebulous_bot/cogs/nextgame.py"), "next_game_notify", "ensure_fresh_cache"),
    ],
)
def test_slow_hybrid_commands_defer_before_work(path, method_name, slow_call):
    method = _method_node(path, method_name)
    assert _awaited_call_line(method, "defer") < _awaited_call_line(method, slow_call)


def test_cancel_notification_defers_before_responding():
    method = _method_node(Path("nebulous_bot/cogs/nextgame.py"), "cancel_next_game_notify")
    defer_line = _awaited_call_line(method, "defer")
    response_lines = [line for line in _awaited_call_lines(method, "send") if line > defer_line]
    assert response_lines
    assert all(defer_line < line for line in response_lines)


def test_stat_limits_are_bounded_for_discord_embeds():
    for command in (StatsCog.show_map_statistics, StatsCog.show_server_statistics):
        parameter = command.app_command.parameters[0]
        assert parameter.min_value == 1
        assert parameter.max_value == 25


def test_stat_limit_prefix_parser_remains_compatible():
    for command in (StatsCog.show_map_statistics, StatsCog.show_server_statistics):
        ctx = SimpleNamespace(
            interaction=None,
            view=StringView("12"),
            message=SimpleNamespace(attachments=[]),
        )
        asyncio.run(command._parse_arguments(ctx))
        assert ctx.args[-1] == 12


def test_immediate_nextgame_notification_clears_deferred_response():
    method = _method_node(Path("nebulous_bot/cogs/nextgame.py"), "next_game_notify")
    assert _awaited_call_line(method, "delete_original_response") > _awaited_call_line(
        method, "notify_single_user_immediately"
    )

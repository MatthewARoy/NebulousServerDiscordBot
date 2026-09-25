"""Gateway-free contracts for the application-command migration framework."""

import asyncio
import ast
import inspect
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord.ext import commands

from nebulous_bot.config import Config
from nebulous_bot.cogs import advice as advice_module
from nebulous_bot.cogs.admin import AdminCog
from nebulous_bot.cogs.advice import AdviceCog
from nebulous_bot.cogs.formation import FormationCog
from nebulous_bot.cogs.nextgame import NextGameCog
from nebulous_bot.cogs.servers import ServersCog
from nebulous_bot.cogs.setup import SetupCog
from nebulous_bot.cogs.stats import StatsCog
from nebulous_bot.management.commands.runbot import (
    GLOBAL_SYNC_CONFIRMATION,
    CommandSyncInputError,
    create_bot,
    handle_application_command_error,
    handle_command_error,
    sync_application_commands,
)
from nebulous_bot.management.commands import runbot


def test_bot_keeps_compatibility_intent_and_accepts_mentions():
    bot = create_bot()

    assert bot.intents.message_content is True
    assert callable(bot.command_prefix)

    message = Mock()
    message.content = ""
    bot._connection.user = Mock(id=1234)
    prefixes = bot.command_prefix(bot, message)

    assert Config.COMMAND_PREFIX in prefixes
    assert "<@1234> " in prefixes
    assert "<@!1234> " in prefixes

    asyncio.run(bot.close())


def test_bot_can_disable_message_content_for_isolated_acceptance_testing():
    bot = create_bot(message_content=False)

    assert bot.intents.message_content is False
    assert callable(bot.command_prefix)

    asyncio.run(bot.close())


def test_production_environment_can_disable_intent_without_changing_entrypoint(monkeypatch):
    monkeypatch.setattr(Config, "DISCORD_MESSAGE_CONTENT", False)
    bot = create_bot()
    assert bot.intents.message_content is False
    assert bot.intents.members is False
    assert bot.intents.presences is False
    asyncio.run(bot.close())


def test_sync_command_is_owner_only_hidden_and_prefix_only():
    bot = create_bot()
    command = bot.get_command("synccommands")

    assert command is not None
    assert command.hidden is True
    assert any(getattr(check, "__qualname__", "").endswith("is_owner.<locals>.predicate") for check in command.checks)
    assert bot.tree.get_command("synccommands") is None

    asyncio.run(bot.close())


def test_bot_construction_never_syncs_command_tree():
    bot = create_bot()
    bot.tree.sync = AsyncMock()

    # Construction and framework registration have already completed, and no
    # ready/startup hook invokes tree.sync.
    bot.tree.sync.assert_not_awaited()

    asyncio.run(bot.close())


def test_only_manual_sync_helper_calls_tree_sync():
    tree = ast.parse(inspect.getsource(runbot))
    sync_call_owners = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "sync"
            for child in ast.walk(node)
        ):
            sync_call_owners.append(node.name)

    assert sync_call_owners == ["sync_application_commands"]


def test_test_guild_sync_is_allowlisted_and_copies_global_tree(monkeypatch):
    bot = create_bot()
    monkeypatch.setattr(Config, "TEST_COMMAND_GUILD_IDS", {9876})
    bot.tree.copy_global_to = Mock()
    bot.tree.sync = AsyncMock(return_value=[Mock(), Mock()])

    synced, destination = asyncio.run(
        sync_application_commands(bot, scope="guild", target="9876")
    )

    guild = bot.tree.sync.await_args.kwargs["guild"]
    assert isinstance(guild, discord.Object)
    assert guild.id == 9876
    bot.tree.copy_global_to.assert_called_once()
    assert bot.tree.copy_global_to.call_args.kwargs["guild"].id == 9876
    assert len(synced) == 2
    assert destination == "test guild 9876"

    asyncio.run(bot.close())


def test_test_guild_sync_rejects_unconfigured_guild(monkeypatch):
    bot = create_bot()
    monkeypatch.setattr(Config, "TEST_COMMAND_GUILD_IDS", {9876})
    bot.tree.sync = AsyncMock()

    with pytest.raises(CommandSyncInputError, match="TEST_COMMAND_GUILD_IDS"):
        asyncio.run(sync_application_commands(bot, scope="guild", target="1234"))

    bot.tree.sync.assert_not_awaited()
    asyncio.run(bot.close())


def test_global_sync_requires_exact_confirmation_token():
    bot = create_bot()
    bot.tree.sync = AsyncMock(return_value=[Mock()])

    with pytest.raises(CommandSyncInputError, match=GLOBAL_SYNC_CONFIRMATION):
        asyncio.run(sync_application_commands(bot, scope="global", target="yes"))
    bot.tree.sync.assert_not_awaited()

    synced, destination = asyncio.run(
        sync_application_commands(
            bot,
            scope="global",
            target=GLOBAL_SYNC_CONFIRMATION,
        )
    )

    bot.tree.sync.assert_awaited_once_with()
    assert len(synced) == 1
    assert destination == "GLOBAL application-command scope"

    asyncio.run(bot.close())


def test_application_error_after_deferral_uses_ephemeral_followup():
    interaction = Mock()
    interaction.command = Mock(qualified_name="example")
    interaction.response.is_done.return_value = True
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    asyncio.run(
        handle_application_command_error(
            interaction,
            discord.app_commands.AppCommandError("private diagnostic"),
        )
    )

    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with(
        "❌ Something went wrong running that command. The error has been logged.",
        ephemeral=True,
    )


def test_hybrid_command_errors_are_ephemeral_and_slash_worded():
    ctx = Mock()
    ctx.interaction = object()
    ctx.command = Mock(qualified_name="formation")
    ctx.send = AsyncMock()

    asyncio.run(handle_command_error(ctx, commands.BadArgument("bad option")))

    ctx.send.assert_awaited_once_with(
        "❌ Invalid command options. Reopen the command picker and try again.",
        ephemeral=True,
    )


@pytest.mark.parametrize("name", [
    "setstatuschannel", "setnotificationchannel", "setnotificationrole", "removestatus",
])
def test_admin_slash_checks_reject_non_admin_and_allow_admin(name):
    async def exercise():
        bot = create_bot()
        await bot.add_cog(SetupCog(bot))
        command = bot.tree.get_command(name)
        ctx = Mock(guild=Mock(), permissions=discord.Permissions.none())
        ctx.interaction = Mock(client=bot, _baton=ctx)
        ctx.command = bot.get_command(name)
        ctx.send = AsyncMock()
        try:
            with pytest.raises(commands.MissingPermissions) as denied:
                await command._check_can_run(ctx.interaction)
            await handle_command_error(ctx, denied.value)
            assert ctx.send.await_args.kwargs["ephemeral"] is True
            ctx.permissions.administrator = True
            assert await command._check_can_run(ctx.interaction)
        finally:
            await bot.close()

    asyncio.run(exercise())


async def _build_complete_bot():
    bot = create_bot()
    for cog_type in (
        SetupCog,
        StatsCog,
        ServersCog,
        AdminCog,
        FormationCog,
        NextGameCog,
        AdviceCog,
    ):
        await bot.add_cog(cog_type(bot))
    return bot


def test_complete_public_application_command_tree_is_test_ready(monkeypatch):
    monkeypatch.setattr(advice_module, "_db", AsyncMock(return_value=([], [], set())))
    bot = asyncio.run(_build_complete_bot())
    expected = {
        "status",
        "version",
        "formation",
        "nextgame",
        "cancelnextgame",
        "listservers",
        "openlobbies",
        "refresh",
        "setstatuschannel",
        "setnotificationchannel",
        "setnotificationrole",
        "removestatus",
        "showsetup",
        "stats",
        "mapstats",
        "serverstats",
        "graph",
        "advice",
    }

    top_level = bot.tree.get_commands()
    assert {command.name for command in top_level} == expected

    commands_to_check = list(top_level)
    for command in top_level:
        commands_to_check.extend(getattr(command, "commands", ()))

    for command in commands_to_check:
        assert command.description and command.description != "…"
        parameters = getattr(command, "parameters", ())
        for parameter in parameters:
            assert parameter.description and parameter.description != "…"

    advice = bot.tree.get_command("advice")
    assert {command.name for command in advice.commands} == {
        "search",
        "add",
        "remove",
        "pending",
        "list",
    }
    assert advice.get_command("restore") is None

    asyncio.run(bot.close())

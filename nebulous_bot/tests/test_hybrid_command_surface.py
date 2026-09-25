"""Contract tests for the first low-risk hybrid-command migration slice."""

import discord

from discord.ext import commands

from nebulous_bot.cogs.admin import AdminCog
from nebulous_bot.cogs.servers import ServersCog
from nebulous_bot.cogs.setup import SetupCog


def _commands_by_name(cog_type):
    return {command.name: command for command in cog_type.__cog_commands__}


def test_public_admin_commands_are_hybrid_but_maintenance_commands_are_not():
    admin_commands = _commands_by_name(AdminCog)

    for name in ("status", "version", "guide"):
        command = admin_commands[name]
        assert isinstance(command, commands.HybridCommand)
        assert command.app_command is not None

    for name in ("restartmonitor", "debugmonitor", "commandlogs"):
        command = admin_commands[name]
        assert type(command) is commands.Command
        assert command.hidden is True
        assert not hasattr(command, "app_command")


def test_setup_commands_are_hybrid_and_keep_prefix_aliases():
    setup_commands = _commands_by_name(SetupCog)
    expected_aliases = {
        "setstatuschannel": ["setstatus"],
        "setnotificationchannel": ["setnotifchannel"],
        "setnotificationrole": ["setnotifrole"],
        "removestatus": ["unsetstatus"],
        "showsetup": ["mysetup", "guildconfig"],
    }

    assert set(setup_commands) == set(expected_aliases)
    for name, aliases in expected_aliases.items():
        command = setup_commands[name]
        assert isinstance(command, commands.HybridCommand)
        assert command.app_command is not None
        assert command.aliases == aliases


def test_server_commands_are_hybrid_and_keep_prefix_aliases():
    server_commands = _commands_by_name(ServersCog)
    expected_aliases = {
        "listservers": ["ls", "servers"],
        "openlobbies": ["open", "available"],
        "refresh": ["update"],
    }

    assert set(server_commands) == set(expected_aliases)
    for name, aliases in expected_aliases.items():
        command = server_commands[name]
        assert isinstance(command, commands.HybridCommand)
        assert command.app_command is not None
        assert command.aliases == aliases


def test_hybrid_commands_have_discord_compatible_descriptions():
    hybrid_commands = (
        *(_commands_by_name(AdminCog).values()),
        *(_commands_by_name(SetupCog).values()),
        *(_commands_by_name(ServersCog).values()),
    )

    for command in hybrid_commands:
        if not isinstance(command, commands.HybridCommand):
            continue
        assert command.app_command.name == command.name
        assert command.app_command.description
        assert len(command.app_command.description) <= 100


def test_hybrid_options_have_discord_compatible_types_and_defaults():
    setup_commands = _commands_by_name(SetupCog)
    server_commands = _commands_by_name(ServersCog)

    status_channel = setup_commands["setstatuschannel"].app_command.parameters
    notification_channel = setup_commands["setnotificationchannel"].app_command.parameters
    notification_role = setup_commands["setnotificationrole"].app_command.parameters
    filters = server_commands["listservers"].app_command.parameters

    assert [(option.name, option.type, option.required) for option in status_channel] == [
        ("channel", discord.AppCommandOptionType.channel, False)
    ]
    assert [(option.name, option.type, option.required) for option in notification_channel] == [
        ("channel", discord.AppCommandOptionType.channel, False)
    ]
    assert [(option.name, option.type, option.required) for option in notification_role] == [
        ("role", discord.AppCommandOptionType.role, True)
    ]
    assert [(option.display_name, option.type, option.required) for option in filters] == [
        ("filters", discord.AppCommandOptionType.string, False)
    ]

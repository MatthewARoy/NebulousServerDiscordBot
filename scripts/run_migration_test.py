"""Run an isolated intent-off application. Never synchronize commands at startup."""
import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
from urllib.request import Request, urlopen

import certifi
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--production-env", type=Path, required=True)
    parser.add_argument("--guild", type=int, required=True)
    parser.add_argument("--check", action="store_true", help="Validate identity without starting the bot")
    args = parser.parse_args()
    test = dotenv_values(args.credentials)
    production = dotenv_values(args.production_env)
    token = test.get("DISCORD_TOKEN")
    application_id = test.get("APPLICATION_ID")
    if not token or not application_id or not application_id.isdigit():
        parser.error("Save a test DISCORD_TOKEN and numeric APPLICATION_ID in the credentials file.")
    if not production.get("DISCORD_TOKEN") or not production.get("APPLICATION_ID"):
        parser.error("Production identity is required to verify isolation.")
    if token == production["DISCORD_TOKEN"] or application_id == production["APPLICATION_ID"]:
        parser.error("Refusing to use the production application's identity.")
    if args.guild <= 0:
        parser.error("A positive test guild ID is required.")

    def get(endpoint):
        request = Request(
            "https://discord.com/api/v10/" + endpoint,
            headers={"Authorization": "Bot " + token, "User-Agent": "NebulousMigrationTest/1.0"},
        )
        with urlopen(request, context=ssl.create_default_context(cafile=certifi.where()), timeout=20) as response:
            return json.load(response)

    application = get("oauth2/applications/@me")
    if str(application["id"]) != application_id:
        parser.error("Token identity does not match the test application ID.")
    guilds = get("users/@me/guilds")
    print(json.dumps({
        "application_id": application_id,
        "application_name": application["name"],
        "guild_installed": any(str(g["id"]) == str(args.guild) for g in guilds),
        "message_content_requested": False,
        "production_identity_distinct": True,
    }), flush=True)
    if args.check:
        return
    if not any(str(g["id"]) == str(args.guild) for g in guilds):
        parser.error("Install the test application in the specified guild first.")
    if any(str(g["id"]) != str(args.guild) for g in guilds):
        parser.error("The test application must be installed only in the designated test guild.")

    root = Path(__file__).resolve().parents[1]
    state = root / ".migration-test"
    state.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "DISCORD_TOKEN": token,
        "APPLICATION_ID": application_id,
        "STEAM_API_KEY": production.get("STEAM_API_KEY", ""),
        "DISCORD_MESSAGE_CONTENT": "false",
        "SERVER_CONFIGS": "[]",
        "DB_PATH": str(state / "db.sqlite3"),
        "TEST_COMMAND_GUILD_IDS": str(args.guild),
        "TEST_COMMAND_BOT_IDS": "",
        "ADVICE_VOTE_THRESHOLD": "1",
        "DJANGO_SETTINGS_MODULE": "nebulous_project.settings",
        "PYTHONUTF8": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    })
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"],
                   cwd=root, env=environment, check=True)
    subprocess.run([sys.executable, "manage.py", "runbot", "--without-message-content"],
                   cwd=root, env=environment, check=True)


if __name__ == "__main__":
    main()

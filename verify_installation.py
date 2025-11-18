#!/usr/bin/env python3
"""
Installation Verification Script for Nebulous Server Discord Bot
Checks that all components are properly installed and configured.
"""

import sys
import os

def check_python_version():
    """Check Python version is 3.8 or higher"""
    print("Checking Python version...", end=" ")
    if sys.version_info < (3, 8):
        print(f"❌ FAIL")
        print(f"   Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"✅ OK (Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})")
    return True

def check_imports():
    """Check all required modules can be imported"""
    print("\nChecking module imports...")
    modules = {
        'discord': 'discord.py',
        'discord.ext.commands': 'discord.py',
        'aiohttp': 'aiohttp',
        'certifi': 'certifi',
        'dotenv': 'python-dotenv',
        'nebulous_bot.config': 'nebulous_bot (local)',
        'nebulous_bot.server_monitor': 'nebulous_bot (local)',
        'nebulous_bot.server_formatter': 'nebulous_bot (local)',
        'nebulous_bot.steam_api': 'nebulous_bot (local)',
    }
    
    all_ok = True
    for module, name in modules.items():
        try:
            __import__(module)
            print(f"  ✅ {name}")
        except ImportError as e:
            print(f"  ❌ {name} - {e}")
            all_ok = False
    
    return all_ok

def check_env_file():
    """Check if .env file exists"""
    print("\nChecking environment configuration...", end=" ")
    if os.path.exists('.env'):
        print("✅ .env file found")
        return True
    else:
        print("⚠️  WARNING: .env file not found")
        print("   Create .env file with your credentials (see env_example.txt)")
        return False

def check_django():
    """Check Django setup"""
    print("\nChecking Django setup...", end=" ")
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nebulous_project.settings')
        django.setup()
        print("✅ OK")
        return True
    except Exception as e:
        print(f"❌ FAIL - {e}")
        return False

def check_file_structure():
    """Check key files exist"""
    print("\nChecking file structure...")
    files = [
        'main.py',
        'run.py',
        'requirements.txt',
        'README.md',
        'nebulous_bot/config.py',
        'nebulous_bot/server_monitor.py',
        'nebulous_bot/server_formatter.py',
        'nebulous_bot/steam_api.py',
    ]
    
    all_ok = True
    for file in files:
        if os.path.exists(file):
            print(f"  ✅ {file}")
        else:
            print(f"  ❌ {file} - MISSING")
            all_ok = False
    
    return all_ok

def test_bot_initialization():
    """Test bot can initialize without errors"""
    print("\nTesting bot initialization...")
    
    # Set dummy env vars for testing
    os.environ.setdefault('DISCORD_TOKEN', 'dummy_token_for_testing')
    os.environ.setdefault('APPLICATION_ID', '123456789')
    os.environ.setdefault('STEAM_API_KEY', 'dummy_steam_key')
    os.environ.setdefault('SERVER_CONFIGS', '[{"guild_id": 123, "status_channel_id": 456}]')
    
    try:
        import discord
        from discord.ext import commands
        from nebulous_bot.config import Config
        from nebulous_bot.server_monitor import ServerMonitor
        from nebulous_bot.server_formatter import ServerFormatter
        
        # Test config
        Config.validate()
        print("  ✅ Config validation")
        
        # Create bot instance
        intents = discord.Intents.default()
        intents.message_content = True
        bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents)
        print("  ✅ Bot instance creation")
        
        # Create components
        monitor = ServerMonitor(bot)
        print("  ✅ ServerMonitor creation")
        
        formatter = ServerFormatter()
        print("  ✅ ServerFormatter creation")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all verification checks"""
    print("=" * 60)
    print("Nebulous Server Discord Bot - Installation Verification")
    print("=" * 60)
    
    results = []
    
    results.append(("Python Version", check_python_version()))
    results.append(("Required Modules", check_imports()))
    results.append(("File Structure", check_file_structure()))
    results.append(("Environment Config", check_env_file()))
    results.append(("Django Setup", check_django()))
    results.append(("Bot Initialization", test_bot_initialization()))
    
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name:.<40} {status}")
    
    all_passed = all(result for _, result in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL CHECKS PASSED")
        print("\nYour bot is ready to run!")
        print("To start the bot: python main.py")
        return 0
    else:
        print("❌ SOME CHECKS FAILED")
        print("\nPlease fix the issues above before running the bot.")
        return 1

if __name__ == "__main__":
    sys.exit(main())


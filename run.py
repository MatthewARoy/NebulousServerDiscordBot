#!/usr/bin/env python3
"""
Simple launcher script for the Nebulous Server Discord Bot
This script provides a clean way to start the bot with proper error handling
"""

import sys
import os
import subprocess
import certifi
from pathlib import Path

def check_requirements():
    """Check if all required files and dependencies are present"""
    required_files = [
        'main.py',
        'config.py', 
        'steam_api.py',
        'server_monitor.py',
        'requirements.txt'
    ]
    
    missing_files = []
    for file in required_files:
        if not Path(file).exists():
            missing_files.append(file)
    
    if missing_files:
        print("❌ Missing required files:")
        for file in missing_files:
            print(f"   - {file}")
        return False
    
    # Check if .env file exists
    if not Path('.env').exists():
        print("⚠️  Warning: .env file not found")
        print("   Create a .env file with your Discord token and Steam API key")
        print("   See README.md for setup instructions")
        return False
    
    return True

def install_dependencies():
    """Install required Python packages"""
    print("📦 Installing dependencies...")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def main():
    """Main launcher function"""
    print("🚀 Nebulous Server Discord Bot Launcher")
    print("=" * 40)
    
    # Check requirements
    if not check_requirements():
        print("\n❌ Pre-flight checks failed. Please fix the issues above.")
        return 1
    
    print("✅ Pre-flight checks passed")
    
    # Skip dependency installation by default
    # install_deps = input("\n📦 Install/update dependencies? (y/n) [n]: ").lower().strip()
    # if install_deps == 'y':
    #     if not install_dependencies():
    #         return 1
    
    # Launch the bot
    print("\n🤖 Starting Nebulous Server Bot...")
    print("   Press Ctrl+C to stop the bot")
    print("-" * 40)
    
    # Set SSL certificate environment variables to fix certificate verification
    cert_path = certifi.where()
    os.environ['SSL_CERT_FILE'] = cert_path
    os.environ['REQUESTS_CA_BUNDLE'] = cert_path
    os.environ['CURL_CA_BUNDLE'] = cert_path
    
    try:
        # Import and run the main bot
        from main import main as bot_main
        bot_main()
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped by user")
        return 0
    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        print("   Try installing dependencies with: pip install -r requirements.txt")
        return 1
    except Exception as e:
        import traceback
        print(f"\n❌ Unexpected error: {e}")
        print("   Full traceback:")
        print(traceback.format_exc())
        print("   Check the logs for more details")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 
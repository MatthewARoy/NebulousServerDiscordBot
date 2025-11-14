#!/usr/bin/env python3
"""
Verification script to check if Django + Azure setup is correct
Run this after conversion to verify everything is properly configured
"""

import os
import sys
from pathlib import Path

print("🔍 Verifying Django + Azure Setup")
print("=" * 50)

errors = []
warnings = []
success = []

# Check Python version
print("\n📋 Checking Python version...")
if sys.version_info >= (3, 8):
    success.append(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} (OK)")
else:
    errors.append(f"❌ Python {sys.version_info.major}.{sys.version_info.minor} (Need 3.8+)")

# Check required files
print("\n📁 Checking required files...")
required_files = [
    'manage.py',
    'Dockerfile',
    'docker-compose.yml',
    'requirements.txt',
    'deploy-azure.sh',
    'nebulous_project/settings.py',
    'nebulous_bot/management/commands/runbot.py',
]

for file in required_files:
    if Path(file).exists():
        success.append(f"✅ {file}")
    else:
        errors.append(f"❌ Missing: {file}")

# Check environment file
print("\n🔐 Checking environment configuration...")
if Path('.env').exists():
    success.append("✅ .env file exists")
    
    # Try to load and check required vars
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        required_env_vars = [
            'DISCORD_TOKEN',
            'APPLICATION_ID',
            'STEAM_API_KEY',
            'SERVER_CONFIGS',
        ]
        
        for var in required_env_vars:
            if os.getenv(var):
                success.append(f"✅ {var} configured")
            else:
                warnings.append(f"⚠️  {var} not set in .env")
    except ImportError:
        warnings.append("⚠️  python-dotenv not installed, skipping env check")
else:
    warnings.append("⚠️  .env file not found (copy from env_example.txt)")

# Check Django can be imported
print("\n🐍 Checking Python dependencies...")
dependencies = [
    'django',
    'discord',
    'aiohttp',
    'dotenv',
    'requests',
]

for dep in dependencies:
    try:
        __import__(dep)
        success.append(f"✅ {dep} installed")
    except ImportError:
        errors.append(f"❌ {dep} not installed")

# Check if Django project can be imported
print("\n🎯 Checking Django project...")
try:
    # Add current directory to path
    sys.path.insert(0, str(Path.cwd()))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nebulous_project.settings')
    
    import django
    django.setup()
    
    from nebulous_bot.models import BotStatus, NotificationLog
    success.append("✅ Django project configured correctly")
    success.append("✅ Models can be imported")
except Exception as e:
    errors.append(f"❌ Django setup error: {e}")

# Check Docker
print("\n🐳 Checking Docker (optional)...")
import subprocess
try:
    result = subprocess.run(['docker', '--version'], capture_output=True, text=True)
    if result.returncode == 0:
        success.append(f"✅ Docker installed: {result.stdout.strip()}")
    else:
        warnings.append("⚠️  Docker not available")
except FileNotFoundError:
    warnings.append("⚠️  Docker not installed (optional for local deployment)")

# Check Azure CLI (optional)
print("\n☁️  Checking Azure CLI (optional)...")
try:
    result = subprocess.run(['az', '--version'], capture_output=True, text=True)
    if result.returncode == 0:
        success.append("✅ Azure CLI installed")
    else:
        warnings.append("⚠️  Azure CLI not available")
except FileNotFoundError:
    warnings.append("⚠️  Azure CLI not installed (optional for Azure deployment)")

# Print summary
print("\n" + "=" * 50)
print("📊 VERIFICATION SUMMARY")
print("=" * 50)

if success:
    print(f"\n✅ Success ({len(success)}):")
    for item in success[:10]:  # Show first 10
        print(f"   {item}")
    if len(success) > 10:
        print(f"   ... and {len(success) - 10} more")

if warnings:
    print(f"\n⚠️  Warnings ({len(warnings)}):")
    for item in warnings:
        print(f"   {item}")

if errors:
    print(f"\n❌ Errors ({len(errors)}):")
    for item in errors:
        print(f"   {item}")

print("\n" + "=" * 50)

if errors:
    print("❌ SETUP INCOMPLETE - Please fix errors above")
    print("\nRun: pip install -r requirements.txt")
    sys.exit(1)
elif warnings:
    print("⚠️  SETUP MOSTLY COMPLETE - Check warnings above")
    print("\n✅ You can run: python manage.py runbot")
    sys.exit(0)
else:
    print("✅ SETUP COMPLETE - All checks passed!")
    print("\n🚀 Next steps:")
    print("   1. Local: python manage.py runbot")
    print("   2. Docker: docker-compose up")
    print("   3. Azure: ./deploy-azure.sh")
    sys.exit(0)


"""Configure Django before importing nebulous_bot modules in tests."""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nebulous_project.settings')
os.environ.setdefault('DISCORD_TOKEN', 'test-token')
os.environ.setdefault('APPLICATION_ID', '0')
os.environ.setdefault('STEAM_API_KEY', 'test-key')

django.setup()

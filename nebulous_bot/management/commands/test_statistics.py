"""
Management command to exercise the statistics tracking system locally.

Creates sample GameSession / PlayerSnapshot rows so !stats, !mapstats,
!serverstats and !graph have data to show against a fresh dev database.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from nebulous_bot.models import GameSession, PlayerSnapshot


class Command(BaseCommand):
    help = 'Create sample statistics data and verify the statistics tables'

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-sample',
            action='store_true',
            help='Create sample game session data for testing',
        )
        parser.add_argument(
            '--verify',
            action='store_true',
            help='Verify the statistics system',
        )

    def handle(self, *args, **options):
        if options['create_sample']:
            self.create_sample_data()

        if options['verify']:
            self.verify_system()

        if not any([options['create_sample'], options['verify']]):
            self.stdout.write(self.style.WARNING('No action specified. Use --help for options.'))

    def create_sample_data(self):
        """Create sample game sessions and player snapshots for testing"""
        self.stdout.write("Creating sample data...")

        now = timezone.now()

        # Create sample game sessions
        maps = ['Arroyo (8P)', 'Pillars (8P)', 'Yukon (8P)', 'Salar (10P)', 'Ralas (10P)']
        servers = [
            ('test_server_1', 'Test Server #1', '192.168.1.100:27015', 'US'),
            ('test_server_2', 'Test Server #2', '192.168.1.101:27015', 'EU'),
            ('test_server_3', 'Test Server #3', '192.168.1.102:27015', 'US'),
        ]

        games_created = 0
        for i in range(20):
            server_id, server_name, server_address, region = servers[i % len(servers)]
            map_name = maps[i % len(maps)]

            game_start = now - timedelta(hours=24 - i, minutes=30)
            game_end = game_start + timedelta(minutes=15 + (i % 10))

            game = GameSession.objects.create(
                server_id=server_id,
                server_name=server_name,
                server_address=server_address,
                map_name=map_name,
                game_mode='Casual Elimination' if i % 2 == 0 else 'Competitive Elimination',
                region=region,
                lobby_start=game_start - timedelta(minutes=5),
                game_start=game_start,
                game_end=game_end,
                players_at_start=6 + (i % 3),
                players_at_end=5 + (i % 3),
                max_players_during_game=8,
                competitive=(i % 2 == 1),
                autobalance=True,
                rank_restricted=False,
            )
            game.calculate_duration()
            game.save()
            games_created += 1

        self.stdout.write(self.style.SUCCESS(f'✓ Created {games_created} sample game sessions'))

        # Create sample player snapshots
        snapshots_created = 0
        for i in range(48):  # Last 24 hours, every 30 minutes
            timestamp = now - timedelta(hours=24 - i * 0.5)
            PlayerSnapshot.objects.create(
                timestamp=timestamp,
                total_players=20 + (i % 15),
                total_servers=3 + (i % 2),
                open_lobbies=1 + (i % 3),
                games_in_progress=2 + (i % 2),
            )
            snapshots_created += 1

        self.stdout.write(self.style.SUCCESS(f'✓ Created {snapshots_created} player snapshots'))

    def verify_system(self):
        """Verify that the statistics tables are populated and consistent"""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("STATISTICS SYSTEM VERIFICATION")
        self.stdout.write("=" * 60 + "\n")

        # Check GameSession
        total_games = GameSession.objects.count()
        valid_games = GameSession.objects.filter(is_valid_game=True).count()
        ongoing_games = GameSession.objects.filter(is_ongoing=True).count()
        self.stdout.write(f"GameSession: {total_games} total, {valid_games} valid, {ongoing_games} ongoing")

        if total_games == 0:
            self.stdout.write(self.style.WARNING("⚠ No game sessions found. Run with --create-sample to add test data."))
        else:
            latest_game = GameSession.objects.order_by('-game_start').first()
            self.stdout.write(f"  Latest: {latest_game.server_name} - {latest_game.map_name}")
            self.stdout.write(f"  Started: {latest_game.game_start}")
            if latest_game.duration_seconds:
                self.stdout.write(f"  Duration: {latest_game.duration_seconds // 60}m {latest_game.duration_seconds % 60}s")

        self.stdout.write("")

        # Check PlayerSnapshot
        total_snapshots = PlayerSnapshot.objects.count()
        self.stdout.write(f"PlayerSnapshot: {total_snapshots} total snapshots")

        if total_snapshots > 0:
            latest_snapshot = PlayerSnapshot.objects.order_by('-timestamp').first()
            self.stdout.write(f"  Latest: {latest_snapshot.total_players} players, {latest_snapshot.total_servers} servers")
            self.stdout.write(f"  Timestamp: {latest_snapshot.timestamp}")
        else:
            self.stdout.write(self.style.WARNING("⚠ No player snapshots found."))

        self.stdout.write("\n" + "=" * 60)

        # Overall health check. Aggregated statistics tables were removed in
        # migration 0005 — !stats and friends compute from GameSession live.
        if total_games > 0 and valid_games > 0:
            self.stdout.write(self.style.SUCCESS("✓ Statistics system is operational"))
        elif total_games > 0:
            self.stdout.write(self.style.WARNING("⚠ Games exist but none are valid (5+ minutes)"))
        else:
            self.stdout.write(self.style.WARNING("⚠ No data collected yet. System is ready but waiting for games."))

        self.stdout.write("=" * 60 + "\n")

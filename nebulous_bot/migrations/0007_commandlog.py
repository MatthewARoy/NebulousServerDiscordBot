from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('nebulous_bot', '0006_add_lobby_wait_tracking'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommandLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('command_name', models.CharField(db_index=True, max_length=100)),
                ('full_command', models.CharField(blank=True, max_length=150)),
                ('user_id', models.BigIntegerField(db_index=True)),
                ('user_name', models.CharField(max_length=255)),
                ('guild_id', models.BigIntegerField(blank=True, db_index=True, null=True)),
                ('guild_name', models.CharField(blank=True, max_length=255)),
                ('channel_id', models.BigIntegerField(blank=True, db_index=True, null=True)),
                ('channel_name', models.CharField(blank=True, max_length=255)),
                ('context_type', models.CharField(default='guild', help_text='Where the command was invoked: guild, dm, or thread', max_length=20)),
                ('message_id', models.BigIntegerField(blank=True, null=True)),
                ('arguments', models.TextField(blank=True)),
                ('success', models.BooleanField(db_index=True, default=True)),
                ('error_type', models.CharField(blank=True, max_length=255)),
                ('latency_ms', models.IntegerField(blank=True, null=True)),
                ('bot_version', models.CharField(blank=True, max_length=50)),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='commandlog',
            index=models.Index(fields=['timestamp', 'command_name'], name='nebulous_b_timesamp_4248dd_idx'),
        ),
        migrations.AddIndex(
            model_name='commandlog',
            index=models.Index(fields=['guild_id', 'command_name'], name='nebulous_b_guild_i_01a4c1_idx'),
        ),
        migrations.AddIndex(
            model_name='commandlog',
            index=models.Index(fields=['user_id', 'command_name'], name='nebulous_b_user_id_6ffb19_idx'),
        ),
    ]



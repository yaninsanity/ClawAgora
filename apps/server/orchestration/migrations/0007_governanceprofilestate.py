from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0006_task_submitted_by"),
    ]

    operations = [
        migrations.CreateModel(
            name="GovernanceProfileState",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("profile", models.CharField(db_index=True, max_length=64, unique=True)),
                ("baseline_weights", models.JSONField(blank=True, default=dict)),
                ("source", models.CharField(blank=True, default="leaderboard", max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]

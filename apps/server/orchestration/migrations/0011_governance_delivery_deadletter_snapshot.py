from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0010_governance_productization_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="GovernanceAlertDelivery",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("event_type", models.CharField(max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("attempt", models.PositiveSmallIntegerField(default=1)),
                ("status", models.CharField(default="pending", max_length=16)),
                ("error", models.CharField(blank=True, default="", max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="orchestration.governancealertsubscription",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="GovernanceAlertDeadLetter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("event_type", models.CharField(max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("last_error", models.CharField(blank=True, default="", max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dead_letters",
                        to="orchestration.governancealertsubscription",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="GovernanceSnapshot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("profile", models.CharField(db_index=True, max_length=64)),
                (
                    "governance_level",
                    models.CharField(blank=True, default="balanced", max_length=16),
                ),
                (
                    "snapshot_type",
                    models.CharField(
                        choices=[("leaderboard", "leaderboard"), ("dashboard", "dashboard")],
                        max_length=16,
                    ),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="governancesnapshot",
            constraint=models.UniqueConstraint(
                fields=("profile", "governance_level", "snapshot_type"),
                name="uniq_governance_snapshot_key",
            ),
        ),
    ]

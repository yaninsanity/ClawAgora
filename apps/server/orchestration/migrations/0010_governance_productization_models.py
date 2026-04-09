from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0009_governanceprofilerevision_change_set"),
    ]

    operations = [
        migrations.AddField(
            model_name="governanceprofilestate",
            name="default_level",
            field=models.CharField(blank=True, default="balanced", max_length=16),
        ),
        migrations.AddField(
            model_name="governanceprofilerevision",
            name="evidence_rows",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="governanceprofilerevision",
            name="governance_level",
            field=models.CharField(blank=True, default="balanced", max_length=16),
        ),
        migrations.AddField(
            model_name="governanceprofilerevision",
            name="impact_scope",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="governanceprofilerevision",
            name="reason",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
        migrations.CreateModel(
            name="GovernanceAlertSubscription",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "profile",
                    models.CharField(
                        db_index=True, default="constitutional_western", max_length=64
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[("webhook", "webhook"), ("slack", "slack"), ("feishu", "feishu")],
                        max_length=16,
                    ),
                ),
                ("target", models.CharField(max_length=512)),
                ("event_types", models.JSONField(blank=True, default=list)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]

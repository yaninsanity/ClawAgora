from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0007_governanceprofilestate"),
    ]

    operations = [
        migrations.CreateModel(
            name="GovernanceProfileRevision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("profile", models.CharField(db_index=True, max_length=64)),
                ("baseline_weights", models.JSONField(blank=True, default=dict)),
                ("source", models.CharField(blank=True, default="leaderboard", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddField(
            model_name="governanceprofilestate",
            name="current_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="orchestration.governanceprofilerevision",
            ),
        ),
    ]

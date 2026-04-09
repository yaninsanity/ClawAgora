from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0011_governance_delivery_deadletter_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="governancealertdeadletter",
            name="replay_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="governancealertdeadletter",
            name="replayed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="governancealertdeadletter",
            name="resolved",
            field=models.BooleanField(default=False),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0005_approval_quorum_vote"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="submitted_by",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]

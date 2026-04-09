from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestration", "0008_governanceprofilerevision_and_state_ptr"),
    ]

    operations = [
        migrations.AddField(
            model_name="governanceprofilerevision",
            name="change_set",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

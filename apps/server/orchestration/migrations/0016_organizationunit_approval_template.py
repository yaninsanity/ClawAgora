import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0015_governance_identity_templates_proposals"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationunit",
            name="approval_template",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="organization_units",
                to="orchestration.approvalpolicytemplate",
            ),
        ),
    ]

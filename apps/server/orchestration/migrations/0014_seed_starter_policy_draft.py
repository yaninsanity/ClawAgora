# Seed an inactive starter policy draft for out-of-box UX. Safe to delete in the UI.

from django.db import migrations


SEED_NAME = "starter-guide (seed)"


def apply_seed(apps, schema_editor):
    PolicyDraft = apps.get_model("orchestration", "PolicyDraft")
    if PolicyDraft.objects.filter(name=SEED_NAME).exists():
        return
    PolicyDraft.objects.create(
        name=SEED_NAME,
        content={
            "_clawagora_seed": True,
            "_guide": (
                "Three-branch model: (1) Legislative — this tab: JSON rules merged into governance; "
                "only one draft can be active. (2) Judicial — Tasks tab: Judicial queue (approvals) "
                "and Needs revision (rework). (3) Executive — left column: Run executes work and "
                "writes receipts. This draft is inactive; Activate to apply deny_patterns and "
                "allowed_executors below, or delete this row."
            ),
            "deny_patterns": [],
        },
        is_active=False,
    )


def remove_seed(apps, schema_editor):
    PolicyDraft = apps.get_model("orchestration", "PolicyDraft")
    PolicyDraft.objects.filter(name=SEED_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0013_three_powers_phase_needs_revision_policy_log_capabilities"),
    ]

    operations = [
        migrations.RunPython(apply_seed, remove_seed),
    ]

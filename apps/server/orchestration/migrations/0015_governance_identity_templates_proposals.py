# Generated manually — organization/subject binding, approval templates, policy evolution proposals.

import uuid

from django.db import migrations, models
import django.db.models.deletion


def seed_approval_templates(apps, schema_editor):
    M = apps.get_model("orchestration", "ApprovalPolicyTemplate")
    seeds = [
        ("single_operator", "Single operator", 1, "First vote resolves (quorum=1). Default single-reviewer UX.", 0),
        (
            "four_eyes",
            "Four-eyes (two approvers)",
            2,
            "Two independent approve votes required (majority threshold = 2). Map to env CLAWAGORA_APPROVAL_QUORUM=2.",
            10,
        ),
        (
            "committee_three",
            "Three-person committee",
            3,
            "Majority of three (threshold = 2). Map to env CLAWAGORA_APPROVAL_QUORUM=3.",
            20,
        ),
    ]
    for slug, name, quorum, desc, order in seeds:
        M.objects.get_or_create(
            slug=slug,
            defaults={
                "name": name,
                "quorum": quorum,
                "description": desc,
                "sort_order": order,
            },
        )


def unseed_approval_templates(apps, schema_editor):
    M = apps.get_model("orchestration", "ApprovalPolicyTemplate")
    M.objects.filter(slug__in=("single_operator", "four_eyes", "committee_three")).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0014_seed_starter_policy_draft"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationUnit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("slug", models.SlugField(db_index=True, max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="children",
                        to="orchestration.organizationunit",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["slug"],
            },
        ),
        migrations.CreateModel(
            name="GovernanceSubject",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("voter_id", models.CharField(db_index=True, max_length=128, unique=True)),
                ("external_subject", models.CharField(blank=True, db_index=True, default="", max_length=256)),
                ("display_name", models.CharField(blank=True, default="", max_length=256)),
                (
                    "org_unit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subjects",
                        to="orchestration.organizationunit",
                    ),
                ),
                (
                    "rank_hint",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional role label (e.g. senior_reviewer) — not enforced by API yet.",
                        max_length=64,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["voter_id"],
            },
        ),
        migrations.CreateModel(
            name="ApprovalPolicyTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(db_index=True, max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("quorum", models.PositiveSmallIntegerField()),
                ("description", models.TextField(blank=True, default="")),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
            ],
            options={
                "ordering": ["sort_order", "slug"],
            },
        ),
        migrations.CreateModel(
            name="PolicyEvolutionProposal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("proposed_content", models.JSONField()),
                ("source", models.CharField(db_index=True, max_length=64)),
                ("rationale", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("accepted", "accepted"),
                            ("rejected", "rejected"),
                            ("superseded", "superseded"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_note", models.CharField(blank=True, default="", max_length=512)),
                (
                    "derived_policy_draft",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="evolution_proposals",
                        to="orchestration.policydraft",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(seed_approval_templates, unseed_approval_templates),
    ]

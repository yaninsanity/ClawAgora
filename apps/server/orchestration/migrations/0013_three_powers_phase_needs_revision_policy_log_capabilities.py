# Generated manually for three-powers rollout: needs_revision + legislative audit + capabilities.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orchestration", "0012_deadletter_replay_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="status",
            field=models.CharField(
                choices=[
                    ("received", "received"),
                    ("queued", "queued"),
                    ("running", "running"),
                    ("completed", "completed"),
                    ("failed", "failed"),
                    ("cancelled", "cancelled"),
                    ("pending_approval", "pending_approval"),
                    ("needs_revision", "needs_revision"),
                ],
                default="received",
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="PolicyActivationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "action",
                    models.CharField(
                        choices=[("activate", "activate"), ("deactivate_all", "deactivate_all")],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "policy_draft",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activation_events",
                        to="orchestration.policydraft",
                    ),
                ),
                (
                    "previous_active",
                    models.ForeignKey(
                        blank=True,
                        help_text="Which draft was active immediately before this event.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="orchestration.policydraft",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="CapabilityBundle",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=128)),
                ("slug", models.SlugField(max_length=128, unique=True)),
                ("source_url", models.TextField(blank=True, default="")),
                ("source_sha256", models.CharField(blank=True, default="", max_length=64)),
                ("notes", models.TextField(blank=True, default="")),
                ("bound_executors", models.JSONField(blank=True, default=list)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
    ]

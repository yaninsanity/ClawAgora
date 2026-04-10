from __future__ import annotations

import uuid

from django.db import models


class Task(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", "received"
        QUEUED = "queued", "queued"
        RUNNING = "running", "running"
        COMPLETED = "completed", "completed"
        FAILED = "failed", "failed"
        # Operator-cancelled before execution started (QUEUED or RECEIVED).
        CANCELLED = "cancelled", "cancelled"
        # Execution paused waiting for human approval.
        PENDING_APPROVAL = "pending_approval", "pending_approval"
        # Judicial rejection (封驳): amend input or policy, then retry — not a terminal failure.
        NEEDS_REVISION = "needs_revision", "needs_revision"

    class RiskTier(models.TextChoices):
        LOW = "low", "low"
        MEDIUM = "medium", "medium"
        HIGH = "high", "high"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_ref = models.CharField(max_length=64, db_index=True, blank=True, default="")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RECEIVED)
    input_text = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    risk_tier = models.CharField(
        max_length=16,
        choices=RiskTier.choices,
        default=RiskTier.LOW,
    )
    classification = models.JSONField(null=True, blank=True)
    plan = models.JSONField(null=True, blank=True)
    validation_reports = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_detail = models.JSONField(null=True, blank=True)
    run_attempt = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
    )
    # Identity of the caller who submitted this task.
    # Set from the X-Submitted-By request header.  Used to enforce proposer ≠
    # approver separation: a voter whose voter_id matches submitted_by is
    # blocked from casting an approve vote on their own task.
    submitted_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TaskEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(Task, related_name="events", on_delete=models.CASCADE)
    sequence = models.PositiveIntegerField()
    phase = models.CharField(max_length=32)
    kind = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence", "id"]
        constraints = [
            models.UniqueConstraint(fields=["task", "sequence"], name="uniq_task_event_sequence")
        ]


class Receipt(models.Model):
    id = models.BigAutoField(primary_key=True)
    task = models.OneToOneField(Task, related_name="receipt", on_delete=models.CASCADE)
    body = models.JSONField()
    body_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)


class PolicyDraft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    content = models.JSONField()
    is_active = models.BooleanField(default=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)


class PolicyActivationEvent(models.Model):
    """Append-only log of legislative policy activations (立法权审计)."""

    class Action(models.TextChoices):
        ACTIVATE = "activate", "activate"
        DEACTIVATE_ALL = "deactivate_all", "deactivate_all"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    policy_draft = models.ForeignKey(
        PolicyDraft,
        null=True,
        blank=True,
        related_name="activation_events",
        on_delete=models.SET_NULL,
    )
    previous_active = models.ForeignKey(
        PolicyDraft,
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.SET_NULL,
        help_text="Which draft was active immediately before this event.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class CapabilityBundle(models.Model):
    """Registered capability / skill metadata (立法层能力登记). Execution still requires Policy allowlists."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True, db_index=True)
    source_url = models.TextField(blank=True, default="")
    source_sha256 = models.CharField(max_length=64, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    bound_executors = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class ApprovalRequest(models.Model):
    """Persisted record of a human approval ticket for a PENDING_APPROVAL task.

    Created by OrchestrationService when a gate returns ApprovalDecision.PENDING.
    Operators approve or reject via POST /api/v1/tasks/<id>/approve|reject/.

    Content schema for PolicyDraft.content (enforced by PolicyDraftWriteSerializer)::

        {
          "allowed_executors": ["executor_coding", ...],  // optional
          "deny_patterns": ["\\bpassword\\b", ...],       // optional
        }
    """

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        APPROVED = "approved", "approved"
        REJECTED = "rejected", "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.OneToOneField(Task, related_name="approval_request", on_delete=models.CASCADE)
    ticket_id = models.CharField(max_length=64)
    risk_tier = models.CharField(max_length=16)
    summary = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    # quorum=1 → single-operator (legacy behaviour).
    # quorum=N → majority vote: need quorum//2+1 votes on the same side.
    quorum = models.PositiveSmallIntegerField(default=1)
    decision_note = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)


class ApprovalVote(models.Model):
    """A single reviewer's vote on an ApprovalRequest.

    unique_together ensures one vote per (request, voter_id).
    The service tallies votes after each cast and auto-resolves the
    ApprovalRequest once the majority threshold (quorum//2+1) is reached.
    """

    class Decision(models.TextChoices):
        APPROVE = "approve", "approve"
        REJECT = "reject", "reject"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    approval_request = models.ForeignKey(
        ApprovalRequest, related_name="votes", on_delete=models.CASCADE
    )
    voter_id = models.CharField(max_length=128)
    decision = models.CharField(max_length=8, choices=Decision.choices)
    rationale = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("approval_request", "voter_id")]


class GovernanceProfileState(models.Model):
    """Persisted baseline weights for a governance profile."""

    profile = models.CharField(max_length=64, unique=True, db_index=True)
    default_level = models.CharField(max_length=16, blank=True, default="balanced")
    baseline_weights = models.JSONField(default=dict, blank=True)
    current_revision = models.ForeignKey(
        "GovernanceProfileRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    source = models.CharField(max_length=64, blank=True, default="leaderboard")
    updated_at = models.DateTimeField(auto_now=True)


class GovernanceProfileRevision(models.Model):
    """Append-only history for governance baseline changes."""

    profile = models.CharField(max_length=64, db_index=True)
    governance_level = models.CharField(max_length=16, blank=True, default="balanced")
    baseline_weights = models.JSONField(default=dict, blank=True)
    change_set = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=256, blank=True, default="")
    evidence_rows = models.JSONField(default=list, blank=True)
    impact_scope = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=64, blank=True, default="leaderboard")
    created_at = models.DateTimeField(auto_now_add=True)


class GovernanceAlertSubscription(models.Model):
    """Operator subscriptions for governance alerts."""

    CHANNEL_CHOICES = (
        ("webhook", "webhook"),
        ("slack", "slack"),
        ("feishu", "feishu"),
    )

    profile = models.CharField(max_length=64, db_index=True, default="constitutional_western")
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES)
    target = models.CharField(max_length=512)
    event_types = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class GovernanceAlertDelivery(models.Model):
    """Delivery attempts per subscription event."""

    subscription = models.ForeignKey(
        GovernanceAlertSubscription, related_name="deliveries", on_delete=models.CASCADE
    )
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    attempt = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, default="pending")
    error = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)


class GovernanceAlertDeadLetter(models.Model):
    """Final failed alert deliveries after max retries."""

    subscription = models.ForeignKey(
        GovernanceAlertSubscription, related_name="dead_letters", on_delete=models.CASCADE
    )
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    replay_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=512, blank=True, default="")
    resolved = models.BooleanField(default=False)
    replayed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class GovernanceSnapshot(models.Model):
    """Cached governance panel payloads for O(1) reads."""

    SNAPSHOT_CHOICES = (
        ("leaderboard", "leaderboard"),
        ("dashboard", "dashboard"),
    )
    profile = models.CharField(max_length=64, db_index=True)
    governance_level = models.CharField(max_length=16, blank=True, default="balanced")
    snapshot_type = models.CharField(max_length=16, choices=SNAPSHOT_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "governance_level", "snapshot_type"],
                name="uniq_governance_snapshot_key",
            )
        ]


class OrganizationUnit(models.Model):
    """Department / org tree for mapping voters to scope (IdP integration hooks)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    approval_template = models.ForeignKey(
        "ApprovalPolicyTemplate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="organization_units",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["slug"]


class GovernanceSubject(models.Model):
    """Binds ``voter_id`` (and optional IdP ``sub``) to org scope for RBAC evolution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    voter_id = models.CharField(max_length=128, unique=True, db_index=True)
    external_subject = models.CharField(max_length=256, blank=True, default="", db_index=True)
    display_name = models.CharField(max_length=256, blank=True, default="")
    org_unit = models.ForeignKey(
        OrganizationUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subjects",
    )
    rank_hint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Optional role label (e.g. senior_reviewer) — not enforced by API yet.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["voter_id"]


class ApprovalPolicyTemplate(models.Model):
    """Named quorum presets (e.g. four-eyes). Runtime quorum still follows CLAWAGORA_APPROVAL_QUORUM."""

    slug = models.SlugField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    quorum = models.PositiveSmallIntegerField()
    description = models.TextField(blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "slug"]


class PolicyEvolutionProposal(models.Model):
    """Suggested policy JSON — must be accepted by a human before becoming a PolicyDraft / activation."""

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        ACCEPTED = "accepted", "accepted"
        REJECTED = "rejected", "rejected"
        SUPERSEDED = "superseded", "superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proposed_content = models.JSONField()
    source = models.CharField(max_length=64, db_index=True)
    rationale = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=512, blank=True, default="")
    derived_policy_draft = models.ForeignKey(
        PolicyDraft,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="evolution_proposals",
    )

    class Meta:
        ordering = ["-created_at"]

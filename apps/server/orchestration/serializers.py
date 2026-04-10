from __future__ import annotations

import json

from django.conf import settings
from rest_framework import serializers

from orchestration.models import (
    ApprovalPolicyTemplate,
    ApprovalRequest,
    ApprovalVote,
    CapabilityBundle,
    GovernanceSubject,
    OrganizationUnit,
    PolicyActivationEvent,
    PolicyDraft,
    PolicyEvolutionProposal,
    Receipt,
    Task,
    TaskEvent,
)
from orchestration.metadata_context import normalize_task_metadata_clawagora_context
from orchestration.policy_content import validate_policy_content_keys


class TaskCreateSerializer(serializers.Serializer):
    input_text = serializers.CharField(
        allow_blank=True,
        max_length=settings.CLAWAGORA_MAX_INPUT_CHARS,
    )
    metadata = serializers.JSONField(required=False, default=dict)

    def validate_metadata(self, value: dict) -> dict:
        raw = json.dumps(value, ensure_ascii=False)
        if len(raw) > settings.CLAWAGORA_MAX_METADATA_BYTES:
            raise serializers.ValidationError("Metadata payload is too large.")
        if len(value) > settings.CLAWAGORA_MAX_METADATA_KEYS:
            raise serializers.ValidationError("Too many metadata keys.")
        return normalize_task_metadata_clawagora_context(value)


class TaskSerializer(serializers.ModelSerializer):
    receipt = serializers.SerializerMethodField()
    error_detail = serializers.SerializerMethodField()
    approval_request = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "external_ref",
            "status",
            "input_text",
            "submitted_by",
            "metadata",
            "risk_tier",
            "classification",
            "plan",
            "validation_reports",
            "error_code",
            "error_detail",
            "run_attempt",
            "receipt",
            "approval_request",
            "created_at",
            "updated_at",
        ]

    def get_receipt(self, obj: Task) -> dict | None:
        rec = getattr(obj, "receipt", None)
        if rec is None:
            return None
        return ReceiptSerializer(rec).data

    def get_approval_request(self, obj: Task) -> dict | None:
        req = getattr(obj, "approval_request", None)
        if req is None:
            return None
        return ApprovalRequestSerializer(req).data

    def get_error_detail(self, obj: Task) -> dict | None:
        if not obj.error_detail:
            return None
        if settings.DEBUG or settings.CLAWAGORA_EXPOSE_ERROR_DETAIL:
            return obj.error_detail
        return {"redacted": True}


class TaskEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskEvent
        fields = ["sequence", "phase", "kind", "payload", "created_at"]


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = ["body", "body_hash", "created_at"]


class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — omits heavy JSON blobs."""

    class Meta:
        model = Task
        fields = [
            "id",
            "status",
            "input_text",
            "risk_tier",
            "error_code",
            "run_attempt",
            "created_at",
            "updated_at",
        ]


class ApprovalVoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalVote
        fields = ["id", "voter_id", "decision", "rationale", "created_at"]


class ApprovalRequestSerializer(serializers.ModelSerializer):
    approve_count = serializers.SerializerMethodField()
    reject_count = serializers.SerializerMethodField()
    threshold = serializers.SerializerMethodField()
    votes = ApprovalVoteSerializer(many=True, read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "ticket_id",
            "risk_tier",
            "summary",
            "status",
            "quorum",
            "approve_count",
            "reject_count",
            "threshold",
            "decision_note",
            "created_at",
            "decided_at",
            "votes",
        ]

    def get_approve_count(self, obj: ApprovalRequest) -> int:
        # Count from the already-loaded votes queryset (uses prefetch cache when
        # available — no extra DB round-trip required).
        return sum(1 for v in obj.votes.all() if v.decision == ApprovalVote.Decision.APPROVE)

    def get_reject_count(self, obj: ApprovalRequest) -> int:
        return sum(1 for v in obj.votes.all() if v.decision == ApprovalVote.Decision.REJECT)

    def get_threshold(self, obj: ApprovalRequest) -> int:
        return obj.quorum // 2 + 1


class PolicyDraftSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyDraft
        fields = ["id", "name", "content", "is_active", "updated_at"]


class PolicyDraftWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    content = serializers.JSONField()

    def validate_content(self, value) -> dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("content must be a JSON object.")
        try:
            validate_policy_content_keys(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        allowed = value.get("allowed_executors")
        if allowed is not None:
            if not isinstance(allowed, list) or not all(isinstance(e, str) for e in allowed):
                raise serializers.ValidationError("allowed_executors must be a list of strings.")
        deny = value.get("deny_patterns")
        if deny is not None:
            if not isinstance(deny, list) or not all(isinstance(p, str) for p in deny):
                raise serializers.ValidationError("deny_patterns must be a list of strings.")
        return value


class OrganizationUnitSerializer(serializers.ModelSerializer):
    approval_template_slug = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationUnit
        fields = ["id", "slug", "name", "parent_id", "approval_template_slug", "created_at"]

    def get_approval_template_slug(self, obj: OrganizationUnit) -> str | None:
        if obj.approval_template_id and getattr(obj, "approval_template", None):
            return obj.approval_template.slug
        return None


class GovernanceSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = GovernanceSubject
        fields = [
            "id",
            "voter_id",
            "external_subject",
            "display_name",
            "org_unit_id",
            "rank_hint",
            "updated_at",
        ]


class ApprovalPolicyTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalPolicyTemplate
        fields = ["slug", "name", "quorum", "description", "sort_order"]


class PolicyEvolutionProposalSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyEvolutionProposal
        fields = [
            "id",
            "proposed_content",
            "source",
            "rationale",
            "status",
            "created_at",
            "resolved_at",
            "resolution_note",
            "derived_policy_draft_id",
        ]


class PolicyEvolutionProposalCreateSerializer(serializers.Serializer):
    proposed_content = serializers.JSONField()
    source = serializers.CharField(max_length=64)
    rationale = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_proposed_content(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("proposed_content must be a JSON object.")
        try:
            validate_policy_content_keys(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        allowed = value.get("allowed_executors")
        if allowed is not None:
            if not isinstance(allowed, list) or not all(isinstance(e, str) for e in allowed):
                raise serializers.ValidationError("allowed_executors must be a list of strings.")
        deny = value.get("deny_patterns")
        if deny is not None:
            if not isinstance(deny, list) or not all(isinstance(p, str) for p in deny):
                raise serializers.ValidationError("deny_patterns must be a list of strings.")
        return value


class PolicyEvolutionProposalResolveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("accept", "reject"))
    draft_name = serializers.CharField(max_length=128, required=False, allow_blank=True)
    note = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")


class TaskAmendSerializer(serializers.Serializer):
    """PATCH body for tasks in needs_revision (or failed) before retry."""

    input_text = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=settings.CLAWAGORA_MAX_INPUT_CHARS,
    )
    metadata = serializers.JSONField(required=False)

    def validate_metadata(self, value: dict) -> dict:
        """Validate the patch only; view merges with existing task metadata then applies limits + clawagora_context."""
        raw = json.dumps(value, ensure_ascii=False)
        if len(raw) > settings.CLAWAGORA_MAX_METADATA_BYTES:
            raise serializers.ValidationError("Metadata patch is too large.")
        if len(value) > settings.CLAWAGORA_MAX_METADATA_KEYS:
            raise serializers.ValidationError("Too many keys in metadata patch.")
        return value


class PolicyActivationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyActivationEvent
        fields = ["id", "action", "policy_draft_id", "previous_active_id", "created_at"]


class CapabilityBundleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapabilityBundle
        fields = [
            "id",
            "name",
            "slug",
            "source_url",
            "source_sha256",
            "notes",
            "bound_executors",
            "is_active",
            "created_at",
            "updated_at",
        ]


class CapabilityBundleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    slug = serializers.SlugField(max_length=128)
    source_url = serializers.CharField(required=False, allow_blank=True, default="")
    source_sha256 = serializers.RegexField(
        r"^$|^[a-fA-F0-9]{64}$", required=False, allow_blank=True, default=""
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    bound_executors = serializers.ListField(
        child=serializers.CharField(max_length=128), required=False, default=list
    )
    is_active = serializers.BooleanField(required=False, default=True)


class CapabilityBundlePatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False)
    source_url = serializers.CharField(required=False, allow_blank=True)
    source_sha256 = serializers.RegexField(
        r"^$|^[a-fA-F0-9]{64}$", required=False, allow_blank=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    bound_executors = serializers.ListField(
        child=serializers.CharField(max_length=128), required=False
    )
    is_active = serializers.BooleanField(required=False)

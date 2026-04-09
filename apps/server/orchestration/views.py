from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.http import Http404
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from clawagora.config import GOVERNANCE_LEVEL_POLICIES
from clawagora.contracts.task import TaskPhase
from clawagora.governance.profile import (
    _PROFILE_ROLES,
    build_governance_context,
    governance_level_policy,
    resolve_governance_level,
)
from clawagora.governance.replay import ReplayBundle, ReplayMode
from orchestration.app_settings import (
    governance_alert_budget_threshold,
    governance_alert_low_efficiency_threshold,
    governance_daily_budget,
    governance_runtime_config,
    governance_snapshot_ttl_seconds,
)
from orchestration.api_exceptions import TaskConflict
from orchestration.capability_policy import validate_active_capability_bundle
from orchestration.execution import resolve_execution_mode
from orchestration.error_codes import CANCELLED, ENQUEUE_FAILED
from orchestration.leaderboard import (
    DASHBOARD_NARRATIVE,
    LEADERBOARD_NARRATIVE,
    leaderboard_reason,
    leaderboard_rows,
    level_meta as _level_meta,
    profile_title as _profile_title,
    today_used_budget,
)
from orchestration.models import (
    ApprovalRequest,
    CapabilityBundle,
    GovernanceAlertDeadLetter,
    GovernanceAlertSubscription,
    GovernanceProfileRevision,
    GovernanceProfileState,
    GovernanceSnapshot,
    PolicyActivationEvent,
    PolicyDraft,
    Task,
    TaskEvent,
)
from orchestration.queue import enqueue_task_execution
from orchestration.serializers import (
    ApprovalVoteSerializer,
    CapabilityBundlePatchSerializer,
    CapabilityBundleSerializer,
    CapabilityBundleWriteSerializer,
    PolicyActivationEventSerializer,
    PolicyDraftSerializer,
    PolicyDraftWriteSerializer,
    ReceiptSerializer,
    TaskAmendSerializer,
    TaskCreateSerializer,
    TaskEventSerializer,
    TaskListSerializer,
    TaskSerializer,
)
from orchestration.permissions import GovernanceWritePermission, PolicyWritePermission
from orchestration.services import get_orchestration_service

logger = logging.getLogger(__name__)

# Default governance profile — overridable via CLAWAGORA_DEFAULT_GOVERNANCE_PROFILE env var.
_DEFAULT_PROFILE: str = settings.CLAWAGORA_DEFAULT_GOVERNANCE_PROFILE
# Default voter identity for legacy single-reviewer approve/reject endpoints.
_DEFAULT_VOTER_ID: str = "operator"


# Alias kept for any local callers within this module.
_leaderboard_rows = leaderboard_rows


def _cache_key(prefix: str, profile: str, level: str = "") -> str:
    marker = Task.objects.filter(metadata__governance_profile=profile).aggregate(
        m=Max("updated_at")
    )["m"]
    marker_str = marker.isoformat() if marker else "none"
    return f"{prefix}:{profile}:{level}:{marker_str}"


def _feedback_decay(*, now, task_time) -> float:
    age_days = max((now - task_time).total_seconds() / timedelta(days=1).total_seconds(), 0.0)
    return 0.5 ** (age_days / 30.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _mark_enqueue_failed(task_id, message: str) -> None:
    Task.objects.filter(pk=task_id).update(
        status=Task.Status.FAILED,
        error_code=ENQUEUE_FAILED,
        error_detail={
            "code": ENQUEUE_FAILED,
            "message": message[:2000],
        },
    )


def _task_kwargs(ser, idempotency_key: str | None, task_status, submitted_by: str = "") -> dict:
    metadata = ser.validated_data.get("metadata") or {}
    profile = str(metadata.get("governance_profile") or "").strip().lower()
    if profile and "governance_level" not in metadata:
        state = GovernanceProfileState.objects.filter(profile=profile).first()
        if state and state.default_level:
            metadata = {**metadata, "governance_level": state.default_level}
    kw: dict = {
        "input_text": ser.validated_data["input_text"],
        "metadata": metadata,
        "status": task_status,
    }
    if idempotency_key:
        kw["idempotency_key"] = idempotency_key
    if submitted_by:
        kw["submitted_by"] = submitted_by
    return kw


class TaskCreateView(APIView):
    def get(self, request):
        """List tasks — supports ?status=, ?risk_tier=, ?q=, ?judicial_queue=, ?limit=, ?offset=."""
        qs = Task.objects.order_by("-created_at")

        status_filter = (request.query_params.get("status") or "").strip()
        if status_filter:
            valid_statuses = {c[0] for c in Task.Status.choices}
            if status_filter not in valid_statuses:
                return Response(
                    {"detail": f"Invalid status. Valid values: {sorted(valid_statuses)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(status=status_filter)

        risk_filter = (request.query_params.get("risk_tier") or "").strip()
        if risk_filter:
            valid_risk = {c[0] for c in Task.RiskTier.choices}
            if risk_filter not in valid_risk:
                return Response(
                    {"detail": f"Invalid risk_tier. Valid values: {sorted(valid_risk)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(risk_tier=risk_filter)

        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(input_text__icontains=q)

        judicial_q = (request.query_params.get("judicial_queue") or "").strip().lower()
        if judicial_q in ("1", "true", "yes"):
            qs = qs.filter(status=Task.Status.PENDING_APPROVAL)

        try:
            cfg = governance_runtime_config()
            limit = min(
                max(int(request.query_params.get("limit", cfg.task_list_default_limit)), 1),
                cfg.task_list_max_limit,
            )
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            return Response(
                {"detail": "limit and offset must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total = qs.count()
        items = list(qs[offset : offset + limit])
        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": TaskListSerializer(items, many=True).data,
            }
        )

    def post(self, request):
        ser = TaskCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        key = (request.headers.get("Idempotency-Key") or "").strip() or None
        submitted_by = (request.headers.get("X-Submitted-By") or "").strip()[:128]
        mode = resolve_execution_mode(request)
        async_mode = mode == "async"
        task_status = Task.Status.QUEUED if async_mode else Task.Status.RECEIVED

        if key:
            existing = Task.objects.filter(idempotency_key=key).first()
            if existing:
                task = Task.objects.select_related("receipt").get(pk=existing.pk)
                return Response(TaskSerializer(task).data, status=status.HTTP_200_OK)
            try:
                task = Task.objects.create(**_task_kwargs(ser, key, task_status, submitted_by))
            except IntegrityError:
                task = Task.objects.select_related("receipt").get(idempotency_key=key)
                return Response(TaskSerializer(task).data, status=status.HTTP_200_OK)
        else:
            task = Task.objects.create(**_task_kwargs(ser, None, task_status, submitted_by))

        if async_mode:
            try:
                enqueue_task_execution(str(task.id))
            except Exception as exc:
                _mark_enqueue_failed(task.id, str(exc))
                return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            task = Task.objects.select_related("receipt").get(pk=task.pk)
            return Response(
                TaskSerializer(task).data,
                status=status.HTTP_202_ACCEPTED,
                headers={"Location": request.build_absolute_uri(f"/api/v1/tasks/{task.id}/")},
            )

        try:
            get_orchestration_service().run_task(task)
        except APIException:
            raise
        except Exception:
            task = Task.objects.select_related("receipt", "approval_request").get(pk=task.pk)
            return Response(
                TaskSerializer(task).data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task.pk)
        )
        # Return 202 when execution is paused waiting for human approval.
        http_status = (
            status.HTTP_202_ACCEPTED
            if task.status == Task.Status.PENDING_APPROVAL
            else status.HTTP_201_CREATED
        )
        return Response(
            TaskSerializer(task).data,
            status=http_status,
            headers={"Location": request.build_absolute_uri(f"/api/v1/tasks/{task.id}/")},
        )


class TaskRetryView(APIView):
    def post(self, request, task_id):
        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()
        mode = resolve_execution_mode(request)
        async_mode = mode == "async"
        try:
            get_orchestration_service().retry_task(task, async_execution=async_mode)
        except APIException:
            raise
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task_id)
        )
        return Response(TaskSerializer(task).data, status=status.HTTP_200_OK)


class TaskAmendView(APIView):
    """PATCH input_text / metadata for tasks in needs_revision or failed (before retry)."""

    def patch(self, request, task_id):
        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()
        if task.status not in (Task.Status.NEEDS_REVISION, Task.Status.FAILED):
            return Response(
                {"detail": "Amend is only allowed for needs_revision or failed tasks."},
                status=status.HTTP_409_CONFLICT,
            )
        ser = TaskAmendSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if not data:
            return Response(
                {"detail": "Provide input_text and/or metadata."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            if locked.status not in (Task.Status.NEEDS_REVISION, Task.Status.FAILED):
                return Response(
                    {"detail": "Task state changed; amend no longer allowed."},
                    status=status.HTTP_409_CONFLICT,
                )
            update_fields = ["updated_at"]
            if "input_text" in data:
                locked.input_text = data["input_text"]
                update_fields.append("input_text")
            if "metadata" in data:
                locked.metadata = data["metadata"]
                update_fields.append("metadata")
            locked.save(update_fields=update_fields)
        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task_id)
        )
        return Response(TaskSerializer(task).data)


class TaskDetailView(APIView):
    def get(self, request, task_id):
        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .filter(id=task_id)
            .first()
        )
        if not task:
            raise Http404()
        return Response(TaskSerializer(task).data)


class TaskTimelineView(APIView):
    def get(self, request, task_id):
        if not Task.objects.filter(id=task_id).exists():
            raise Http404()
        events = TaskEvent.objects.filter(task_id=task_id).order_by("sequence", "id")
        return Response(TaskEventSerializer(events, many=True).data)


class TaskReceiptView(APIView):
    def get(self, request, task_id):
        task = Task.objects.select_related("receipt").filter(id=task_id).first()
        if not task:
            raise Http404()
        rec = getattr(task, "receipt", None)
        if rec is None:
            raise Http404()
        return Response(ReceiptSerializer(rec).data)


# ---------------------------------------------------------------------------
# Human approval flow
# ---------------------------------------------------------------------------


class TaskApproveView(APIView):
    """Approve a PENDING_APPROVAL task by casting an approve vote.

    For quorum=1 (default) this resolves immediately and (optionally) runs
    the pipeline inline or enqueues it via the X-ClawAgora-Execution header.
    For quorum>1 a single approve vote is cast; the task remains
    PENDING_APPROVAL until the majority threshold is reached.

    Body (optional): {"voter_id": "alice", "note": "reason"}
    voter_id defaults to "operator" when omitted (single-reviewer compat).
    """

    def post(self, request, task_id):
        data = request.data if isinstance(request.data, dict) else {}
        voter_id = (data.get("voter_id") or _DEFAULT_VOTER_ID).strip()[:128]
        note = (data.get("note") or "")[:512]
        mode = resolve_execution_mode(request)
        async_mode = mode == "async"

        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()

        try:
            task, resolution = get_orchestration_service().cast_vote(
                task,
                voter_id=voter_id,
                decision="approve",
                rationale=note,
                async_execution=async_mode,
            )
        except APIException:
            raise
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task_id)
        )
        logger.info(
            "task_approved task_id=%s voter=%s resolution=%s async=%s",
            task_id,
            voter_id,
            resolution,
            async_mode,
        )
        http_status = status.HTTP_202_ACCEPTED if resolution == "pending" else status.HTTP_200_OK
        return Response(TaskSerializer(task).data, status=http_status)


class TaskRejectView(APIView):
    """Reject a PENDING_APPROVAL task by casting a reject vote.

    For quorum=1 this immediately marks the task ``needs_revision``.
    For quorum>1 a single reject vote is cast; the task stays
    PENDING_APPROVAL until the rejection threshold is reached.

    Body (optional): {"voter_id": "alice", "note": "reason"}
    """

    def post(self, request, task_id):
        data = request.data if isinstance(request.data, dict) else {}
        voter_id = (data.get("voter_id") or _DEFAULT_VOTER_ID).strip()[:128]
        note = (data.get("note") or "")[:512]

        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()

        try:
            task, resolution = get_orchestration_service().cast_vote(
                task,
                voter_id=voter_id,
                decision="reject",
                rationale=note,
            )
        except APIException:
            raise
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task_id)
        )
        logger.info(
            "task_rejected task_id=%s voter=%s resolution=%s", task_id, voter_id, resolution
        )
        http_status = status.HTTP_202_ACCEPTED if resolution == "pending" else status.HTTP_200_OK
        return Response(TaskSerializer(task).data, status=http_status)


class TaskVoteView(APIView):
    """Cast a named vote on a pending approval request.

    This is the primary multi-reviewer endpoint.  Each voter_id may cast
    exactly one vote.  The service auto-resolves the request once the
    majority threshold (quorum//2 + 1) is reached on either side.

    Body: {"voter_id": "alice", "decision": "approve"|"reject", "rationale": "..."}

    Returns:
        202 — vote recorded, quorum not yet reached.
        200 — quorum reached; task either running (approve) or needs_revision (reject).
    """

    def post(self, request, task_id):
        if not isinstance(request.data, dict):
            return Response({"detail": "Invalid body."}, status=status.HTTP_400_BAD_REQUEST)
        voter_id = (request.data.get("voter_id") or "").strip()[:128]
        decision = (request.data.get("decision") or "").strip()
        rationale = (request.data.get("rationale") or "")[:2000]

        if not voter_id:
            return Response({"detail": "voter_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if decision not in ("approve", "reject"):
            return Response(
                {"detail": "decision must be 'approve' or 'reject'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()

        mode = resolve_execution_mode(request)
        async_mode = mode == "async"

        try:
            task, resolution = get_orchestration_service().cast_vote(
                task,
                voter_id=voter_id,
                decision=decision,
                rationale=rationale,
                async_execution=async_mode,
            )
        except APIException:
            raise
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task_id)
        )
        http_status = status.HTTP_202_ACCEPTED if resolution == "pending" else status.HTTP_200_OK
        return Response(TaskSerializer(task).data, status=http_status)


class TaskVotesView(APIView):
    """List all votes cast on a task's approval request."""

    def get(self, request, task_id):
        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()
        ar = ApprovalRequest.objects.filter(task=task).first()
        if not ar:
            raise Http404()
        votes = ar.votes.order_by("created_at")
        return Response(ApprovalVoteSerializer(votes, many=True).data)


class GovernanceFeedbackView(APIView):
    """Apply manual governance accountability feedback to a task.

    POST /api/v1/governance/feedback/
    Body:
      {
        "task_id": "<uuid>",
        "source": "operator",
        "entries": [{"role": "...", "delta": 0.1, "incidents": 0, "reason": "..."}]
      }
    """

    permission_classes = [GovernanceWritePermission]

    def post(self, request):
        if not isinstance(request.data, dict):
            return Response({"detail": "Invalid body."}, status=status.HTTP_400_BAD_REQUEST)
        task_id = request.data.get("task_id")
        source = str(request.data.get("source") or "operator").strip()[:64] or "operator"
        entries = request.data.get("entries")
        if not task_id:
            return Response({"detail": "task_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(entries, list) or not entries:
            return Response(
                {"detail": "entries must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        normalized: list[dict] = []
        for idx, item in enumerate(entries, start=1):
            if not isinstance(item, dict):
                return Response(
                    {"detail": f"entries[{idx}] must be an object."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            role = str(item.get("role") or "").strip()
            if not role:
                return Response(
                    {"detail": f"entries[{idx}].role is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                delta = float(item.get("delta", 0.0))
                incidents = int(float(item.get("incidents", 0)))
            except (TypeError, ValueError):
                return Response(
                    {"detail": f"entries[{idx}] has invalid delta/incidents."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            normalized.append(
                {
                    "role": role,
                    "delta": delta,
                    "incidents": max(incidents, 0),
                    "reason": str(item.get("reason") or "")[:256],
                }
            )
        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()
        profile = str((task.metadata or {}).get("governance_profile") or "").strip().lower()
        if profile in _PROFILE_ROLES:
            allowed = set(_PROFILE_ROLES[profile])
            unknown = [e["role"] for e in normalized if e["role"] not in allowed]
            if unknown:
                return Response(
                    {"detail": f"Unknown role(s) for profile '{profile}': {unknown}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        task = get_orchestration_service().submit_governance_feedback(
            task, normalized, source=source
        )
        return Response(TaskSerializer(task).data, status=status.HTTP_200_OK)


class GovernanceStatusView(APIView):
    """Return governance loop state, efficiency signals, and narrative framing."""

    def get(self, request, task_id):
        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()
        timeline = list(TaskEvent.objects.filter(task=task).order_by("sequence", "id"))
        governance_events = [e for e in timeline if e.phase == TaskPhase.GOVERNANCE.value]
        feedback = task.metadata.get("accountability_feedback")
        feedback = feedback if isinstance(feedback, list) else []
        ctx = build_governance_context(task.metadata or {})
        cycle_seconds = max(int((task.updated_at - task.created_at).total_seconds()), 0)
        total_events = len(timeline)
        governance_ratio = round(len(governance_events) / total_events, 4) if total_events else 0.0
        profile_title = _profile_title(ctx.profile)
        payload = {
            "task_id": str(task.id),
            "profile": ctx.profile,
            "governance_level": ctx.level,
            "profile_title": profile_title,
            "narrative_stage": self._narrative_stage(task.status),
            "roles": list(ctx.roles),
            "role_weights": ctx.role_weights,
            "latest_feedback": feedback[-10:],
            "efficiency": {
                "cycle_seconds": cycle_seconds,
                "total_events": total_events,
                "governance_events": len(governance_events),
                "governance_event_ratio": governance_ratio,
                "run_attempt": task.run_attempt,
            },
            "governance_timeline": [
                {
                    "sequence": e.sequence,
                    "kind": e.kind,
                    "payload": e.payload,
                    "created_at": e.created_at.isoformat(),
                }
                for e in governance_events[-20:]
            ],
        }
        return Response(payload, status=status.HTTP_200_OK)

    @staticmethod
    def _narrative_stage(task_status: str) -> str:
        if task_status == Task.Status.PENDING_APPROVAL:
            return "Judicial Review Board Deliberation"
        if task_status == Task.Status.RUNNING:
            return "Executive Dispatch In Progress"
        if task_status == Task.Status.COMPLETED:
            return "Inspector General Post-Run Audit"
        if task_status == Task.Status.FAILED:
            return "Constitutional Remediation"
        return "Intake and Policy Drafting"


class GovernanceProfilesView(APIView):
    """Return governance level cards and allow selecting default profile level."""

    permission_classes = [GovernanceWritePermission]

    def get(self, request):
        profile = (request.query_params.get("profile") or _DEFAULT_PROFILE).strip().lower()
        state = GovernanceProfileState.objects.filter(profile=profile).first()
        selected = state.default_level if state else "balanced"
        # Per-level display metadata lives in leaderboard._LEVEL_META registry so
        # operators adding a new entry to GOVERNANCE_LEVEL_POLICIES + calling
        # register_level_meta() get correct labels without any view changes.
        cards = []
        for level in GOVERNANCE_LEVEL_POLICIES:
            p = governance_level_policy(level)
            meta = _level_meta(level)
            cards.append(
                {
                    "level": level,
                    "latency_estimate": meta["latency_estimate"],
                    "risk_control": meta["risk_control"],
                    "cost_estimate": meta["cost_estimate"],
                    "policy": p,
                    "selected": level == selected,
                }
            )
        return Response({"profile": profile, "selected_level": selected, "cards": cards})

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        profile = str(body.get("profile") or _DEFAULT_PROFILE).strip().lower()
        level = resolve_governance_level({"governance_level": body.get("level")})
        state, _ = GovernanceProfileState.objects.update_or_create(
            profile=profile,
            defaults={"default_level": level},
        )
        return Response(
            {"profile": profile, "selected_level": state.default_level}, status=status.HTTP_200_OK
        )


class GovernanceLeaderboardView(APIView):
    """Cross-task governance performance and next-round weight suggestions."""

    def get(self, request):
        cfg = governance_runtime_config()
        profile = (request.query_params.get("profile") or _DEFAULT_PROFILE).strip().lower()
        limit_param = request.query_params.get("limit", str(cfg.list_default_limit))
        try:
            limit = min(max(int(limit_param), 1), cfg.list_max_limit)
        except (TypeError, ValueError):
            return Response(
                {"detail": f"limit must be an integer between 1 and {cfg.list_max_limit}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        snap = GovernanceSnapshot.objects.filter(
            profile=profile, governance_level="", snapshot_type="leaderboard"
        ).first()
        if (
            snap
            and (timezone.now() - snap.updated_at).total_seconds()
            <= governance_snapshot_ttl_seconds()
        ):
            cached = dict(snap.payload or {})
        else:
            ck = _cache_key("governance_leaderboard", profile)
            cached = cache.get(ck)
        if not cached:
            ranked, scanned = _leaderboard_rows(profile, scan_limit=cfg.leaderboard_scan_limit)
            baseline = GovernanceProfileState.objects.filter(profile=profile).first()
            cached = {
                "profile": profile,
                "narrative": LEADERBOARD_NARRATIVE,
                "tasks_scanned": scanned,
                "roles_ranked": len(ranked),
                "applied_baseline": (baseline.baseline_weights if baseline else {}),
                "roles": ranked,
            }
            cache.set(ck, cached, timeout=cfg.response_cache_ttl_seconds)
        out = dict(cached)
        out["roles"] = list(cached["roles"])[:limit]
        return Response(out, status=status.HTTP_200_OK)

    @staticmethod
    def _reason(success_rate: float, incident_rate: float, avg_delta: float) -> str:
        return leaderboard_reason(success_rate, incident_rate, avg_delta)


class GovernanceDashboardView(APIView):
    """Operator-facing governance panel payload."""

    def get(self, request):
        cfg = governance_runtime_config()
        profile = (request.query_params.get("profile") or _DEFAULT_PROFILE).strip().lower()
        level = resolve_governance_level(
            {"governance_level": request.query_params.get("governance_level")}
        )
        snap = GovernanceSnapshot.objects.filter(
            profile=profile, governance_level=level, snapshot_type="dashboard"
        ).first()
        if (
            snap
            and (timezone.now() - snap.updated_at).total_seconds()
            <= governance_snapshot_ttl_seconds()
        ):
            return Response(snap.payload, status=status.HTTP_200_OK)
        ck = _cache_key("governance_dashboard", profile, level)
        cached = cache.get(ck)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)
        budget = governance_daily_budget(level)
        budget_threshold = governance_alert_budget_threshold()
        efficiency_threshold = governance_alert_low_efficiency_threshold()
        used = GovernanceApplyRecommendationsView._today_used_budget(profile)
        ranked, scanned = _leaderboard_rows(profile, scan_limit=cfg.leaderboard_scan_limit)
        top = ranked[:10]
        remaining = {role: round(max(budget - used_amt, 0.0), 4) for role, used_amt in used.items()}
        alerts = []
        for role, used_amt in used.items():
            ratio = used_amt / budget if budget > 0 else 1.0
            if ratio >= budget_threshold:
                alerts.append(
                    {
                        "type": "budget_near_exhausted",
                        "role": role,
                        "used": round(used_amt, 4),
                        "budget": round(budget, 4),
                        "usage_ratio": round(ratio, 4),
                    }
                )
        for item in top:
            if item["efficiency_score"] < efficiency_threshold:
                alerts.append(
                    {
                        "type": "low_efficiency",
                        "role": item["role"],
                        "efficiency_score": item["efficiency_score"],
                        "recommended_weight": item["recommended_weight"],
                    }
                )
        baseline = GovernanceProfileState.objects.filter(profile=profile).first()
        payload = {
            "profile": profile,
            "governance_level": level,
            "narrative": DASHBOARD_NARRATIVE,
            "tasks_scanned": scanned,
            "daily_budget": round(budget, 4),
            "daily_budget_used": {k: round(v, 4) for k, v in used.items()},
            "daily_budget_remaining": remaining,
            "applied_baseline": (baseline.baseline_weights if baseline else {}),
            "leaderboard_top": top,
            "alerts": alerts[:25],
        }
        cache.set(ck, payload, timeout=cfg.response_cache_ttl_seconds)
        return Response(payload, status=status.HTTP_200_OK)


class GovernanceLeaderboardHistoryView(APIView):
    """Trend view for recent governance revisions."""

    def get(self, request):
        cfg = governance_runtime_config()
        profile = (request.query_params.get("profile") or _DEFAULT_PROFILE).strip().lower()
        limit = min(
            max(int(request.query_params.get("limit", cfg.list_default_limit)), 1),
            cfg.list_max_limit,
        )
        revs = GovernanceProfileRevision.objects.filter(profile=profile).order_by(
            "-created_at", "-id"
        )[:limit]
        rows = [
            {
                "revision_id": r.id,
                "created_at": r.created_at.isoformat(),
                "governance_level": r.governance_level,
                "source": r.source,
                "reason": r.reason,
                "change_set": r.change_set,
                "impact_scope": r.impact_scope,
            }
            for r in revs
        ]
        return Response({"profile": profile, "history": rows}, status=status.HTTP_200_OK)


class GovernanceBudgetForecastView(APIView):
    """Forecast daily budget exhaustion using recent apply velocity."""

    def get(self, request):
        profile = (request.query_params.get("profile") or _DEFAULT_PROFILE).strip().lower()
        level = resolve_governance_level(
            {"governance_level": request.query_params.get("governance_level")}
        )
        budget = governance_daily_budget(level)
        used = GovernanceApplyRecommendationsView._today_used_budget(profile)
        recent = GovernanceProfileRevision.objects.filter(profile=profile).order_by(
            "-created_at", "-id"
        )[:30]
        velocity: dict[str, float] = defaultdict(float)
        span_hours = 24.0
        if recent:
            oldest = recent[len(recent) - 1].created_at
            newest = recent[0].created_at
            span_hours = max((newest - oldest).total_seconds() / 3600.0, 1.0)
        for r in recent:
            if not isinstance(r.change_set, dict):
                continue
            for role, delta in r.change_set.items():
                try:
                    velocity[str(role)] += abs(float(delta))
                except (TypeError, ValueError):
                    continue
        out = []
        for role, used_amt in used.items():
            vph = velocity.get(role, 0.0) / span_hours
            remaining = max(budget - used_amt, 0.0)
            eta_hours = None if vph <= 0 else round(remaining / vph, 2)
            out.append(
                {
                    "role": role,
                    "used_today": round(used_amt, 4),
                    "budget": round(budget, 4),
                    "remaining": round(remaining, 4),
                    "velocity_per_hour": round(vph, 4),
                    "eta_hours_to_exhaustion": eta_hours,
                }
            )
        return Response(
            {"profile": profile, "governance_level": level, "forecast": out},
            status=status.HTTP_200_OK,
        )


class GovernanceAlertSubscriptionsView(APIView):
    """Manage governance alert subscriptions (webhook/slack/feishu)."""

    permission_classes = [GovernanceWritePermission]

    def get(self, request):
        profile = (request.query_params.get("profile") or _DEFAULT_PROFILE).strip().lower()
        subs = GovernanceAlertSubscription.objects.filter(profile=profile).order_by("-updated_at")
        return Response(
            [
                {
                    "id": s.id,
                    "profile": s.profile,
                    "channel": s.channel,
                    "target": s.target,
                    "event_types": s.event_types,
                    "enabled": s.enabled,
                }
                for s in subs
            ],
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        profile = str(body.get("profile") or _DEFAULT_PROFILE).strip().lower()
        channel = str(body.get("channel") or "").strip().lower()
        target = str(body.get("target") or "").strip()
        event_types = body.get("event_types") or ["budget_near_exhausted", "low_efficiency"]
        if channel not in {"webhook", "slack", "feishu"}:
            return Response(
                {"detail": "channel must be webhook|slack|feishu."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not target:
            return Response({"detail": "target is required."}, status=status.HTTP_400_BAD_REQUEST)
        sub = GovernanceAlertSubscription.objects.create(
            profile=profile,
            channel=channel,
            target=target,
            event_types=event_types if isinstance(event_types, list) else [],
            enabled=bool(body.get("enabled", True)),
        )
        return Response(
            {"id": sub.id, "profile": profile, "channel": channel, "target": target},
            status=status.HTTP_201_CREATED,
        )


class GovernanceDeadLettersView(APIView):
    """List dead-letter records for governance alerts."""

    permission_classes = [GovernanceWritePermission]

    def get(self, request):
        cfg = governance_runtime_config()
        profile = (request.query_params.get("profile") or _DEFAULT_PROFILE).strip().lower()
        try:
            limit = min(
                max(int(request.query_params.get("limit", cfg.dead_letter_default_limit)), 1),
                cfg.dead_letter_max_limit,
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "limit must be an integer."}, status=status.HTTP_400_BAD_REQUEST
            )
        rows = (
            GovernanceAlertDeadLetter.objects.filter(subscription__profile=profile)
            .select_related("subscription")
            .order_by("-created_at")[:limit]
        )
        return Response(
            [
                {
                    "id": r.id,
                    "profile": r.subscription.profile,
                    "channel": r.subscription.channel,
                    "target": r.subscription.target,
                    "event_type": r.event_type,
                    "attempts": r.attempts,
                    "replay_count": r.replay_count,
                    "resolved": r.resolved,
                    "last_error": r.last_error,
                    "created_at": r.created_at.isoformat(),
                    "replayed_at": r.replayed_at.isoformat() if r.replayed_at else None,
                }
                for r in rows
            ],
            status=status.HTTP_200_OK,
        )


class GovernanceDeadLetterReplayView(APIView):
    """Replay dead-letter deliveries."""

    permission_classes = [GovernanceWritePermission]

    def post(self, request):
        from orchestration.jobs import replay_governance_dead_letters_job

        cfg = governance_runtime_config()
        body = request.data if isinstance(request.data, dict) else {}
        try:
            limit = max(int(body.get("limit", cfg.dead_letter_default_limit)), 1)
        except (TypeError, ValueError):
            return Response(
                {"detail": "limit must be an integer."}, status=status.HTTP_400_BAD_REQUEST
            )
        dry_run = bool(body.get("dry_run", False))
        profile = str(body.get("profile") or "").strip().lower() or None
        event_type = str(body.get("event_type") or "").strip().lower() or None
        return Response(
            replay_governance_dead_letters_job(
                limit=limit,
                profile=profile,
                event_type=event_type,
                dry_run=dry_run,
            ),
            status=status.HTTP_200_OK,
        )


class GovernanceApplyRecommendationsView(APIView):
    """Apply leaderboard recommendations into profile baseline weights."""

    permission_classes = [GovernanceWritePermission]

    def post(self, request):
        cfg = governance_runtime_config()
        body = request.data if isinstance(request.data, dict) else {}
        profile = str(body.get("profile") or _DEFAULT_PROFILE).strip().lower()
        level = resolve_governance_level({"governance_level": body.get("governance_level")})
        policy = governance_level_policy(level)
        daily_budget = governance_daily_budget(level)
        source = str(body.get("source") or "auto_apply").strip()[:64] or "auto_apply"
        reason = str(body.get("reason") or "Leaderboard-driven adaptive update").strip()[:256]
        evidence_rows = body.get("evidence_rows") or []
        if not isinstance(evidence_rows, list):
            evidence_rows = []
        dry_run = bool(body.get("dry_run", False))
        limit_raw = body.get("limit", cfg.list_default_limit)
        try:
            limit = min(max(int(limit_raw), 1), cfg.list_max_limit)
        except (TypeError, ValueError):
            return Response(
                {"detail": f"limit must be an integer between 1 and {cfg.list_max_limit}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ranked, scanned = _leaderboard_rows(profile, scan_limit=cfg.leaderboard_scan_limit)
        if not ranked:
            return Response(
                {
                    "profile": profile,
                    "updated": False,
                    "detail": "No governance feedback data available for this profile.",
                },
                status=status.HTTP_200_OK,
            )
        selected = ranked[:limit]
        baseline: dict[str, float] = {}
        current = GovernanceProfileState.objects.filter(profile=profile).first()
        current_weights = current.baseline_weights if current else {}
        today_used = self._today_used_budget(profile)
        for item in selected:
            role = item["role"]
            old = float(current_weights.get(role, 1.0))
            target = float(item["recommended_weight"])
            blended = old + ((target - old) * policy["apply_alpha"])
            step = _clamp(blended - old, -policy["max_step_change"], policy["max_step_change"])
            remaining = max(daily_budget - today_used.get(role, 0.0), 0.0)
            if abs(step) > remaining:
                step = remaining if step >= 0 else -remaining
            baseline[role] = round(_clamp(old + step, 0.2, 2.0), 4)
        diff = {
            role: {"old": float(current_weights.get(role, 1.0)), "new": float(weight)}
            for role, weight in baseline.items()
            if float(current_weights.get(role, 1.0)) != float(weight)
        }
        if dry_run:
            return Response(
                {
                    "profile": profile,
                    "updated": False,
                    "dry_run": True,
                    "tasks_scanned": scanned,
                    "roles_candidate": len(baseline),
                    "governance_level": level,
                    "daily_budget": daily_budget,
                    "diff": diff,
                },
                status=status.HTTP_200_OK,
            )
        change_set = {
            role: round(float(weight) - float(current_weights.get(role, 1.0)), 4)
            for role, weight in baseline.items()
            if float(weight) != float(current_weights.get(role, 1.0))
        }
        revision = GovernanceProfileRevision.objects.create(
            profile=profile,
            governance_level=level,
            baseline_weights=baseline,
            change_set=change_set,
            reason=reason,
            evidence_rows=evidence_rows[:50],
            impact_scope={
                "roles_changed": len(change_set),
                "tasks_scanned": scanned,
                "governance_level": level,
            },
            source=source,
        )
        state, _ = GovernanceProfileState.objects.update_or_create(
            profile=profile,
            defaults={
                "baseline_weights": baseline,
                "source": source,
                "current_revision": revision,
            },
        )
        return Response(
            {
                "profile": profile,
                "updated": True,
                "source": source,
                "tasks_scanned": scanned,
                "roles_applied": len(baseline),
                "governance_level": level,
                "daily_budget": daily_budget,
                "baseline_weights": state.baseline_weights,
                "revision_id": revision.id,
                "why": reason,
                "evidence_rows": revision.evidence_rows,
                "impact_scope": revision.impact_scope,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _today_used_budget(profile: str) -> dict[str, float]:
        return today_used_budget(profile)


class GovernanceRollbackView(APIView):
    """Rollback profile baseline weights to the previous revision."""

    permission_classes = [GovernanceWritePermission]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        profile = str(body.get("profile") or _DEFAULT_PROFILE).strip().lower()
        reason_template = str(
            body.get("reason_template")
            or "Rollback executed due to governance risk, budget breach, or quality regression."
        ).strip()[:256]
        revisions = list(
            GovernanceProfileRevision.objects.filter(profile=profile).order_by(
                "-created_at", "-id"
            )[:2]
        )
        if len(revisions) < 2:
            return Response(
                {
                    "profile": profile,
                    "rolled_back": False,
                    "detail": "No previous revision available.",
                },
                status=status.HTTP_200_OK,
            )
        target = revisions[1]
        state, _ = GovernanceProfileState.objects.update_or_create(
            profile=profile,
            defaults={
                "baseline_weights": target.baseline_weights,
                "source": "rollback",
                "current_revision": target,
            },
        )
        GovernanceProfileRevision.objects.create(
            profile=profile,
            governance_level=(target.governance_level or "balanced"),
            baseline_weights=target.baseline_weights,
            change_set={},
            reason=reason_template,
            impact_scope={
                "rollback_to_revision": target.id,
                "roles_changed": len(target.baseline_weights),
            },
            source="rollback",
        )
        return Response(
            {
                "profile": profile,
                "rolled_back": True,
                "baseline_weights": state.baseline_weights,
                "revision_id": target.id,
                "reason_template": reason_template,
                "impact_scope": {"roles_changed": len(target.baseline_weights)},
            },
            status=status.HTTP_200_OK,
        )


class TaskInjectView(APIView):
    """Inject operator guidance into task metadata.

    Allowed for PENDING_APPROVAL, FAILED, and RECEIVED tasks.
    Body: {"guidance": "..."}
    Guidance is appended to metadata["guidance_notes"] and available to
    the pipeline on the next execution run.
    """

    def post(self, request, task_id):
        guidance = (
            (request.data.get("guidance") or "").strip() if isinstance(request.data, dict) else ""
        )
        if not guidance:
            return Response(
                {"detail": "guidance must be a non-empty string."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()
        try:
            get_orchestration_service().inject_guidance(task, guidance)
        except APIException:
            raise
        task = (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task_id)
        )
        return Response(TaskSerializer(task).data)


# ---------------------------------------------------------------------------
# Task cancellation
# ---------------------------------------------------------------------------


class TaskCancelView(APIView):
    """Cancel a task that has not yet entered execution.

    Only RECEIVED and QUEUED tasks can be cancelled. RUNNING, COMPLETED,
    FAILED, and CANCELLED tasks return 409. Cancellation is idempotent-safe:
    calling cancel on an already-CANCELLED task returns 409 with a clear message.
    """

    _CANCELLABLE = frozenset({Task.Status.RECEIVED, Task.Status.QUEUED})

    def post(self, request, task_id):
        with transaction.atomic():
            task = Task.objects.select_for_update().filter(id=task_id).first()
            if not task:
                raise Http404()
            if task.status not in self._CANCELLABLE:
                return Response(
                    {
                        "detail": (
                            f"Cannot cancel a task in status '{task.status}'. "
                            f"Only {sorted(s.value for s in self._CANCELLABLE)} tasks can be cancelled."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            task.status = Task.Status.CANCELLED
            task.error_code = CANCELLED
            task.error_detail = {"code": CANCELLED}
            task.save(update_fields=["status", "error_code", "error_detail", "updated_at"])

        task = Task.objects.select_related("receipt").get(pk=task_id)
        return Response(TaskSerializer(task).data)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class TaskReplayView(APIView):
    """Return a ReplayBundle reconstructed from stored TaskEvents.

    Query params:
      ?mode=events     (default) — all timeline events in sequence order.
      ?mode=decisions  — classification, validation, and terminal events only,
                         suitable for policy-outcome forensic replay.
    """

    _DECISION_PHASES = frozenset(
        {TaskPhase.CLASSIFY.value, TaskPhase.VALIDATE.value, TaskPhase.TERMINAL.value}
    )

    def get(self, request, task_id):
        if not Task.objects.filter(id=task_id).exists():
            raise Http404()

        mode_str = (request.query_params.get("mode") or "events").lower()
        if mode_str not in ("events", "decisions"):
            return Response(
                {"detail": "mode must be 'events' or 'decisions'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = TaskEvent.objects.filter(task_id=task_id).order_by("sequence", "id")
        if mode_str == "decisions":
            qs = qs.filter(phase__in=self._DECISION_PHASES)

        records = [
            {
                "sequence": e.sequence,
                "phase": e.phase,
                "kind": e.kind,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
            }
            for e in qs
        ]
        bundle = ReplayBundle(
            mode=ReplayMode(mode_str),
            task_id=str(task_id),
            records=records,
        )
        return Response(bundle.model_dump())


# ---------------------------------------------------------------------------
# Policy Draft CRUD
# ---------------------------------------------------------------------------


class PolicyDraftListView(APIView):
    """List and create PolicyDraft records.

    PolicyDrafts store versioned policy documents for operator review.
    The *active* draft (is_active=True) is enforced at runtime by the
    PolicyValidator and SafetyValidator via DB-backed loaders.
    """

    permission_classes = [PolicyWritePermission]

    def get(self, request):
        drafts = PolicyDraft.objects.order_by("-updated_at")
        return Response(PolicyDraftSerializer(drafts, many=True).data)

    def post(self, request):
        ser = PolicyDraftWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        draft = PolicyDraft.objects.create(**ser.validated_data)
        return Response(PolicyDraftSerializer(draft).data, status=status.HTTP_201_CREATED)


class PolicyDraftDetailView(APIView):
    """Retrieve, update, or delete a single PolicyDraft."""

    permission_classes = [PolicyWritePermission]

    def _get_draft(self, draft_id) -> PolicyDraft:
        obj = PolicyDraft.objects.filter(id=draft_id).first()
        if obj is None:
            raise Http404()
        return obj

    def get(self, request, draft_id):
        return Response(PolicyDraftSerializer(self._get_draft(draft_id)).data)

    def put(self, request, draft_id):
        draft = self._get_draft(draft_id)
        ser = PolicyDraftWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        for key, val in ser.validated_data.items():
            setattr(draft, key, val)
        draft.save()
        return Response(PolicyDraftSerializer(draft).data)

    def patch(self, request, draft_id):
        draft = self._get_draft(draft_id)
        ser = PolicyDraftWriteSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        for key, val in ser.validated_data.items():
            setattr(draft, key, val)
        draft.save()
        return Response(PolicyDraftSerializer(draft).data)

    def delete(self, request, draft_id):
        self._get_draft(draft_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PolicyDraftActivateView(APIView):
    """Atomically activate one PolicyDraft, deactivating all others.

    POST /api/v1/policies/<id>/activate/ — activates this draft.
    POST /api/v1/policies/deactivate/    — deactivates all drafts.

    The active draft’s content is enforced at execution time:
      - content.allowed_executors overrides the PolicyValidator default allowlist.
      - content.deny_patterns overrides the SafetyValidator default deny list.
    """

    permission_classes = [PolicyWritePermission]

    def post(self, request, draft_id=None):
        with transaction.atomic():
            previous_active = PolicyDraft.objects.filter(is_active=True).first()
            PolicyDraft.objects.update(is_active=False)
            if draft_id is not None:
                draft = PolicyDraft.objects.select_for_update().filter(id=draft_id).first()
                if not draft:
                    raise Http404()
                draft.is_active = True
                draft.save(update_fields=["is_active", "updated_at"])
                draft.refresh_from_db()
                PolicyActivationEvent.objects.create(
                    action=PolicyActivationEvent.Action.ACTIVATE,
                    policy_draft=draft,
                    previous_active=(
                        previous_active
                        if previous_active and previous_active.pk != draft.pk
                        else None
                    ),
                )
                cache.delete("orchestration:active_policy")
                return Response(PolicyDraftSerializer(draft).data)
            PolicyActivationEvent.objects.create(
                action=PolicyActivationEvent.Action.DEACTIVATE_ALL,
                policy_draft=None,
                previous_active=previous_active,
            )
        cache.delete("orchestration:active_policy")
        return Response({"detail": "All policies deactivated."}, status=status.HTTP_200_OK)


class PolicyActivationLogListView(APIView):
    """GET legislative policy activation history (立法审计)."""

    def get(self, request):
        try:
            cfg = governance_runtime_config()
            limit = min(
                max(int(request.query_params.get("limit", 50)), 1),
                cfg.list_max_limit,
            )
        except (ValueError, TypeError):
            return Response(
                {"detail": "limit must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = PolicyActivationEvent.objects.order_by("-created_at")[:limit]
        return Response(PolicyActivationEventSerializer(qs, many=True).data)


class CapabilityBundleListView(APIView):
    """List and register capability / skill bundles (立法层元数据)."""

    permission_classes = [PolicyWritePermission]

    def get(self, request):
        active_only = (request.query_params.get("active_only") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        qs = CapabilityBundle.objects.order_by("-updated_at")
        if active_only:
            qs = qs.filter(is_active=True)
        return Response(CapabilityBundleSerializer(qs, many=True).data)

    def post(self, request):
        ser = CapabilityBundleWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        if d.get("is_active", True):
            validate_active_capability_bundle(
                source_url=d.get("source_url") or "",
                source_sha256=d.get("source_sha256") or "",
            )
        bundle = CapabilityBundle.objects.create(
            name=d["name"],
            slug=d["slug"],
            source_url=d.get("source_url") or "",
            source_sha256=d.get("source_sha256") or "",
            notes=d.get("notes") or "",
            bound_executors=list(d.get("bound_executors") or []),
            is_active=d.get("is_active", True),
        )
        return Response(CapabilityBundleSerializer(bundle).data, status=status.HTTP_201_CREATED)


class CapabilityBundleDetailView(APIView):
    permission_classes = [PolicyWritePermission]

    def _get(self, bundle_id) -> CapabilityBundle:
        obj = CapabilityBundle.objects.filter(id=bundle_id).first()
        if obj is None:
            raise Http404()
        return obj

    def get(self, request, bundle_id):
        return Response(CapabilityBundleSerializer(self._get(bundle_id)).data)

    def patch(self, request, bundle_id):
        bundle = self._get(bundle_id)
        ser = CapabilityBundlePatchSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        for key, val in ser.validated_data.items():
            setattr(bundle, key, val)
        if bundle.is_active:
            validate_active_capability_bundle(
                source_url=bundle.source_url,
                source_sha256=bundle.source_sha256,
            )
        bundle.save()
        return Response(CapabilityBundleSerializer(bundle).data)

    def delete(self, request, bundle_id):
        self._get(bundle_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OpenClawIntegrationStatusView(APIView):
    """GET OpenClaw gateway probe (Phase 3 — optional external runtime)."""

    def get(self, request):
        from django.conf import settings as dj_settings

        from orchestration.openclaw_client import probe_gateway
        from orchestration.openclaw_delegate import build_delegate_status_snapshot

        delegate = build_delegate_status_snapshot(dj_settings)

        if not getattr(dj_settings, "CLAWAGORA_OPENCLAW_ENABLED", False):
            return Response(
                {
                    "enabled": False,
                    "reachable": False,
                    "detail": "Set CLAWAGORA_OPENCLAW_ENABLED=1 to probe the gateway.",
                    "delegate": delegate,
                }
            )
        timeout = float(getattr(dj_settings, "CLAWAGORA_OPENCLAW_STATUS_TIMEOUT_SEC", 3.0))
        result = probe_gateway(
            gateway_url=dj_settings.CLAWAGORA_OPENCLAW_GATEWAY_URL,
            api_key=dj_settings.CLAWAGORA_OPENCLAW_API_KEY,
            timeout_sec=timeout,
        )
        return Response(
            {
                "enabled": result.enabled,
                "gateway_url": result.gateway_url,
                "reachable": result.reachable,
                "http_status": result.http_status,
                "latency_ms": result.latency_ms,
                "detail": result.detail,
                "body_preview": result.body_preview,
                "delegate": delegate,
            }
        )


class OpenClawCallbackView(APIView):
    """POST callback from an OpenClaw-compatible bridge when external agents finish.

    Raw body must be JSON. Requires ``X-ClawAgora-Signature`` HMAC-SHA256 of the raw
    bytes when ``CLAWAGORA_OPENCLAW_WEBHOOK_SECRET`` is set. Optional replay protection
    uses ``X-ClawAgora-Timestamp`` + ``X-ClawAgora-Nonce``.
    """

    def post(self, request):
        from django.conf import settings as dj_settings

        from orchestration.openclaw_delegate import verify_callback_guard, verify_callback_signature

        raw = request.body
        sig = request.headers.get("X-ClawAgora-Signature") or request.META.get(
            "HTTP_X_CLAWAGORA_SIGNATURE"
        )
        ts = request.headers.get("X-ClawAgora-Timestamp") or request.META.get(
            "HTTP_X_CLAWAGORA_TIMESTAMP"
        )
        nonce = request.headers.get("X-ClawAgora-Nonce") or request.META.get(
            "HTTP_X_CLAWAGORA_NONCE"
        )
        secret = getattr(dj_settings, "CLAWAGORA_OPENCLAW_WEBHOOK_SECRET", "") or ""
        if not secret or not verify_callback_signature(secret, raw, sig or ""):
            return Response(
                {"detail": "invalid or missing signature"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if getattr(dj_settings, "CLAWAGORA_OPENCLAW_CALLBACK_REQUIRE_GUARD", True):
            ok, reason = verify_callback_guard(
                timestamp_header=ts,
                nonce_header=nonce,
                max_skew_sec=int(
                    getattr(dj_settings, "CLAWAGORA_OPENCLAW_CALLBACK_MAX_SKEW_SEC", 300)
                ),
                nonce_ttl_sec=int(
                    getattr(dj_settings, "CLAWAGORA_OPENCLAW_CALLBACK_NONCE_TTL_SEC", 900)
                ),
            )
            if not ok:
                return Response(
                    {"detail": f"callback guard rejected: {reason}"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        import json

        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return Response({"detail": "invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(data, dict):
            return Response({"detail": "body must be a JSON object"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            task = get_orchestration_service().apply_openclaw_callback(data)
        except TaskConflict as exc:
            return Response({"detail": str(exc.detail)}, status=exc.status_code)
        except Http404:
            raise Http404()
        return Response(TaskSerializer(task).data)


class OpenClawDelegateTriggerView(APIView):
    """Set ``metadata.openclaw.delegate`` (and optional ``agents``) then run the task."""

    def post(self, request, task_id):
        task = Task.objects.filter(id=task_id).first()
        if not task:
            raise Http404()
        if task.status not in (Task.Status.RECEIVED, Task.Status.QUEUED):
            return Response(
                {"detail": "Task must be received or queued."},
                status=status.HTTP_409_CONFLICT,
            )
        data = request.data if isinstance(request.data, dict) else {}
        agents = data.get("agents")
        if agents is not None:
            if not isinstance(agents, list) or not all(isinstance(a, (str, int, float, bool)) for a in agents):
                return Response(
                    {"detail": "agents must be an array of scalar values."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        md = dict(task.metadata or {})
        oc = dict(md.get("openclaw") if isinstance(md.get("openclaw"), dict) else {})
        oc["delegate"] = True
        if isinstance(agents, list):
            oc["agents"] = [str(a) for a in agents]
        md["openclaw"] = oc
        task.metadata = md
        task.save(update_fields=["metadata", "updated_at"])
        mode = resolve_execution_mode(request)
        async_mode = mode == "async"
        try:
            if async_mode:
                try:
                    enqueue_task_execution(str(task.id))
                except Exception as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                task = Task.objects.select_related("receipt", "approval_request").get(pk=task_id)
            else:
                get_orchestration_service().run_task(task)
                task = Task.objects.select_related("receipt", "approval_request").get(pk=task_id)
        except APIException:
            raise
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(TaskSerializer(task).data)

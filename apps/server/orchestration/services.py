from __future__ import annotations

import logging
import uuid
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from clawagora.contracts.task import TaskPhase, TaskState
from clawagora.governance.approval import ApprovalDecision, ApprovalTicket, HumanApprovalGate
from clawagora.governance.gates import AutoApprovalGate
from clawagora.governance.risk import RiskClassifier
from clawagora.kernel.classify import ClassifyService
from clawagora.kernel.dispatcher import Dispatcher
from clawagora.kernel.executors.base import ExecutorRegistry
from clawagora.kernel.executors.builtin import EchoExecutor, TransformExecutor
from clawagora.kernel.executors.domain import CodingExecutor, ResearchExecutor, SupportExecutor
from clawagora.kernel.intake import IntakeService
from clawagora.kernel.pipeline import PipelineResult, TaskPipeline
from clawagora.kernel.planner import PlannerService
from clawagora.kernel.synthesizer import Synthesizer
from clawagora.kernel.validation import (
    CompositeValidator,
    PolicyValidator,
    SafetyValidator,
    SchemaValidator,
)
from clawagora.providers.base import ModelProvider
from clawagora.runtime.execution import build_rollback_plan
from clawagora.runtime.opt_engine import OptimizationEngine
from clawagora.cost import CostPolicy
from clawagora.runtime.accountability import (
    accountability_feedback_from_result,
    governance_loop_snapshot,
    merge_accountability_feedback,
)
from clawagora.runtime.trust_computer import TrustScoreComputer
from clawagora.stores.receipt_store import hash_body

from orchestration.api_exceptions import TaskConflict, TaskInProgress
from orchestration.error_codes import (
    APPROVAL_REJECTED,
    ENQUEUE_FAILED,
    MISSING_SYNTHESIS,
    OPENCLAW_DELEGATE_FAILED,
    PIPELINE_INVARIANT_FAILED,
)
from orchestration.logging_support import bind_task_context, reset_task_context
from orchestration.prompt_circuit import merge_circuit_overrides_into_metadata, record_prompt_circuit_outcome
from orchestration.models import (
    ApprovalRequest,
    GovernanceProfileState,
    Receipt,
    Task,
    TaskEvent,
)
from orchestration.queue import enqueue_task_execution

logger = logging.getLogger(__name__)


def _build_model_provider() -> ModelProvider:
    """Construct the configured ModelProvider from app_settings.ModelConfig.

    All setting access is delegated to ``model_config()`` which reads from
    ``django.conf.settings``; this function only constructs the object.
    """
    from clawagora.providers.null_provider import NullModelProvider
    from orchestration.app_settings import model_config

    cfg = model_config()
    cost_policy = CostPolicy(
        input_cost_per_mtok_usd=cfg.input_cost_per_mtok_usd,
        output_cost_per_mtok_usd=cfg.output_cost_per_mtok_usd,
        token_chars_estimate=cfg.token_chars_estimate,
    )
    if cfg.provider == "ollama":
        from clawagora.providers.ollama import OllamaModelProvider

        return OllamaModelProvider(
            base_url=cfg.url,
            model_name=cfg.name,
            timeout_secs=cfg.timeout,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            cost_policy=cost_policy,
        )
    if cfg.provider == "openai_compat":
        from clawagora.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            base_url=cfg.url,
            model_name=cfg.name,
            api_key=cfg.api_key,
            timeout_secs=cfg.timeout,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            cost_policy=cost_policy,
        )
    return NullModelProvider()


def _cost_policy_from_model_config() -> CostPolicy:
    from orchestration.app_settings import model_config

    cfg = model_config()
    return CostPolicy(
        input_cost_per_mtok_usd=cfg.input_cost_per_mtok_usd,
        output_cost_per_mtok_usd=cfg.output_cost_per_mtok_usd,
        token_chars_estimate=cfg.token_chars_estimate,
    )


def _load_active_policy() -> tuple[set[str] | None, list[str] | None]:
    """Return (allowed_executors, deny_patterns) from the active PolicyDraft, or (None, None).

    Result is cached for 5 seconds so that calling this twice within the same
    pipeline run (once from ``PolicyValidator``, once from ``SafetyValidator``)
    only incurs a single database round-trip.
    """
    from django.core.cache import cache as _cache

    _CACHE_KEY = "orchestration:active_policy"
    cached = _cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    from orchestration.models import PolicyDraft

    draft = PolicyDraft.objects.filter(is_active=True).first()
    if draft is None:
        result: tuple[set[str] | None, list[str] | None] = (None, None)
    else:
        content = draft.content or {}
        executors = content.get("allowed_executors")
        patterns = content.get("deny_patterns")
        result = (
            set(executors) if isinstance(executors, list) else None,
            patterns if isinstance(patterns, list) else None,
        )
    _cache.set(_CACHE_KEY, result, timeout=5)
    return result


def _build_default_gate():
    """Construct the configured HumanApprovalGate from app_settings.

    Reads CLAWAGORA_APPROVAL_GATE, CLAWAGORA_APPROVAL_QUORUM, and the
    review/reject tier settings.  Defaults to AutoApprovalGate so existing
    deployments are unaffected until operators opt in by setting the env var.
    """
    from orchestration.app_settings import approval_gate_config

    cfg = approval_gate_config()
    if cfg.mode == "pending_human":
        from clawagora.governance.gates import PendingHumanApprovalGate
        from clawagora.governance.risk import RiskTier

        tier = (
            RiskTier(cfg.review_at)
            if cfg.review_at in (t.value for t in RiskTier)
            else RiskTier.HIGH
        )
        return PendingHumanApprovalGate(review_at=tier, quorum=cfg.quorum)
    if cfg.mode == "risk_based":
        from clawagora.governance.gates import RiskBasedApprovalGate
        from clawagora.governance.risk import RiskTier

        tier = (
            RiskTier(cfg.reject_at)
            if cfg.reject_at in (t.value for t in RiskTier)
            else RiskTier.HIGH
        )
        return RiskBasedApprovalGate(reject_at=tier)
    return AutoApprovalGate()


def build_default_pipeline() -> TaskPipeline:
    model = _build_model_provider()
    cost_policy = _cost_policy_from_model_config()
    validators = CompositeValidator(
        [
            SchemaValidator(),
            PolicyValidator(
                policy_loader=lambda: _load_active_policy()[0],
            ),
            SafetyValidator(
                deny_loader=lambda: _load_active_policy()[1],
            ),
        ]
    )
    registry = ExecutorRegistry(
        [
            # Generic built-ins (used for "general" intent / unmatched labels)
            TransformExecutor(),
            EchoExecutor(),
            # Domain executors (CODING / RESEARCH / SUPPORT packs)
            CodingExecutor(),
            ResearchExecutor(),
            SupportExecutor(),
        ]
    )
    return TaskPipeline(
        intake=IntakeService(),
        classify=ClassifyService(model=model, cost_policy=cost_policy),
        planner=PlannerService(),
        validators=validators,
        dispatcher=Dispatcher(),
        registry=registry,
        synthesizer=Synthesizer(model=model, cost_policy=cost_policy),
        max_workers=settings.CLAWAGORA_EXECUTOR_POOL_SIZE,
    )


_DEFAULT_EXECUTOR_LABELS: dict[str, str] = {
    "executor_transform": "Transform",
    "executor_echo": "Echo",
    "executor_coding": "Coding",
    "executor_research": "Research",
    "executor_support": "Support",
}


def list_default_pipeline_executors() -> list[dict[str, str]]:
    """Ids and labels for executors on the default TaskPipeline (legislative allowlist source of truth)."""
    pipeline = build_default_pipeline()
    out: list[dict[str, str]] = []
    for eid in pipeline._registry.registered_executor_ids():
        out.append({"id": eid, "label": _DEFAULT_EXECUTOR_LABELS.get(eid, eid)})
    return out


class OrchestrationService:
    def __init__(
        self,
        pipeline: TaskPipeline | None = None,
        gate: HumanApprovalGate | None = None,
    ) -> None:
        from orchestration.app_settings import risk_keyword_config

        risk_cfg = risk_keyword_config()
        self._pipeline = pipeline or build_default_pipeline()
        self._risk = RiskClassifier(
            high_patterns=risk_cfg.high_patterns,
            medium_patterns=risk_cfg.medium_patterns,
        )
        # Approval gate — defaults to the setting-configured gate.
        # Pass gate=AutoApprovalGate() in tests to bypass review, or inject
        # a PendingHumanApprovalGate(quorum=N) via CLAWAGORA_APPROVAL_GATE.
        self._gate = gate or _build_default_gate()
        # Trust score and optimisation are computed after every successful run.
        self._trust = TrustScoreComputer()
        self._opt = OptimizationEngine()

    def run_task(self, task: Task) -> Task:
        # Bind task_id into the logging context for the duration of this call.
        # This makes every log line (including kernel logs) carry task_id=<uuid>
        # whether execution is synchronous or via the async worker.
        _ctx = bind_task_context(str(task.id))
        try:
            return self._run_task_inner(task)
        finally:
            reset_task_context(_ctx)

    def run_task_approved(self, task: Task) -> Task:
        """Resume execution for a task that has been explicitly approved by a human.

        Must only be called after the ApprovalRequest has been set to APPROVED
        (done atomically by the approve view). Skips the approval gate entirely.
        """
        _ctx = bind_task_context(str(task.id))
        try:
            return self._run_task_inner(task, skip_approval=True)
        finally:
            reset_task_context(_ctx)

    def cast_vote(
        self,
        task: Task,
        *,
        voter_id: str,
        decision: str,
        rationale: str = "",
        async_execution: bool = False,
    ) -> tuple[Task, str]:
        """Cast one reviewer's vote on a pending approval request.

        Returns ``(task, resolution)`` where *resolution* is one of:
        - ``"pending"``  — vote recorded; quorum not yet reached.
        - ``"approved"`` — majority approved; execution started/enqueued.
        - ``"rejected"`` — majority rejected; task marked ``needs_revision`` (司法封驳返工).

        quorum=1 (the default) means the first vote resolves immediately,
        preserving backward-compatible single-operator behaviour.

        Governance checks enforced here (not in the view) so they apply
        regardless of call path (API, management command, test):

        1. Voter allowlist: if CLAWAGORA_APPROVAL_ALLOWED_VOTERS is non-empty,
           voter_id must appear in it (司法权边界).
        2. Self-approval block: a voter cannot approve their own submission
           (task.submitted_by == voter_id is rejected for approve votes).
        """
        from rest_framework.exceptions import PermissionDenied as _PermissionDenied

        from orchestration.app_settings import allowed_voters as _allowed_voters
        from orchestration.models import ApprovalVote
        from django.db import IntegrityError as _IntegrityError
        from django.utils import timezone

        # ── 司法权：voter allowlist check ────────────────────────────────────
        voters = _allowed_voters()
        if voters and voter_id not in voters:
            raise _PermissionDenied(f"Voter '{voter_id}' is not in the authorised reviewer list.")

        # ── 提案人自批禁止：proposer ≠ approver ───────────────────────────────
        if decision == "approve" and task.submitted_by and task.submitted_by == voter_id:
            raise _PermissionDenied(
                f"Voter '{voter_id}' submitted this task and cannot approve their own submission."
            )

        resolution = "pending"
        approve_count = reject_count = threshold = 0

        with transaction.atomic():
            locked_task = Task.objects.select_for_update().filter(pk=task.pk).first()
            if not locked_task or locked_task.status != Task.Status.PENDING_APPROVAL:
                raise TaskConflict(detail="Task is not awaiting approval.")

            ar = (
                ApprovalRequest.objects.select_for_update()
                .filter(task=locked_task, status=ApprovalRequest.Status.PENDING)
                .first()
            )
            if not ar:
                raise TaskConflict(detail="No pending approval request for this task.")

            try:
                ApprovalVote.objects.create(
                    approval_request=ar,
                    voter_id=voter_id,
                    decision=decision,
                    rationale=rationale,
                )
            except _IntegrityError:
                raise TaskConflict(
                    detail=f"Voter '{voter_id}' has already cast a vote on this request."
                )

            threshold = ar.quorum // 2 + 1
            approve_count = ar.votes.filter(decision=ApprovalVote.Decision.APPROVE).count()
            reject_count = ar.votes.filter(decision=ApprovalVote.Decision.REJECT).count()
            now = timezone.now()

            if approve_count >= threshold:
                resolution = "approved"
                ar.status = ApprovalRequest.Status.APPROVED
                ar.decision_note = f"Quorum reached: {approve_count}/{ar.quorum} approved."
                ar.decided_at = now
                ar.save(update_fields=["status", "decision_note", "decided_at"])
                if async_execution:
                    locked_task.status = Task.Status.QUEUED
                    locked_task.save(update_fields=["status", "updated_at"])
            elif reject_count >= threshold:
                resolution = "rejected"
                ar.status = ApprovalRequest.Status.REJECTED
                ar.decision_note = f"Quorum reached: {reject_count}/{ar.quorum} rejected."
                ar.decided_at = now
                ar.save(update_fields=["status", "decision_note", "decided_at"])
                locked_task.status = Task.Status.NEEDS_REVISION
                locked_task.error_code = APPROVAL_REJECTED
                locked_task.error_detail = {
                    "code": APPROVAL_REJECTED,
                    "branch": "judicial",
                    "remediation": "retry_after_edit",
                    "hint": "Amend input_text or metadata, then POST /api/v1/tasks/<id>/retry/.",
                    "votes_reject": reject_count,
                    "quorum": ar.quorum,
                }
                locked_task.save(
                    update_fields=["status", "error_code", "error_detail", "updated_at"]
                )

        task.refresh_from_db()

        if resolution == "approved":
            logger.info(
                "task_vote_quorum_approved task_id=%s voter=%s approve=%s quorum=%s",
                task.id,
                voter_id,
                approve_count,
                ar.quorum,
            )
            if async_execution:
                try:
                    enqueue_task_execution(str(task.id))
                except Exception as exc:
                    logger.warning("enqueue_failed task_id=%s error=%s", task.id, exc)
                    Task.objects.filter(pk=task.pk).update(
                        status=Task.Status.FAILED,
                        error_code=ENQUEUE_FAILED,
                        error_detail={"code": ENQUEUE_FAILED, "message": str(exc)[:2000]},
                    )
                    task.refresh_from_db()
            else:
                self.run_task_approved(task)
        elif resolution == "rejected":
            logger.info(
                "task_vote_quorum_rejected task_id=%s voter=%s reject=%s quorum=%s",
                task.id,
                voter_id,
                reject_count,
                ar.quorum,
            )
        else:
            logger.info(
                "task_vote_cast task_id=%s voter=%s decision=%s approve=%s reject=%s threshold=%s",
                task.id,
                voter_id,
                decision,
                approve_count,
                reject_count,
                threshold,
            )

        task.refresh_from_db()
        return task, resolution

    def _run_task_inner(self, task: Task, *, skip_approval: bool = False) -> Task:
        delegate_openclaw = False
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            if skip_approval:
                # Approved via approve endpoint: accept both PENDING_APPROVAL (sync path)
                # and QUEUED (async path — view transitioned state before enqueuing).
                if locked.status not in (Task.Status.PENDING_APPROVAL, Task.Status.QUEUED):
                    raise TaskConflict(detail="Task is not awaiting approval.")
            else:
                if locked.status == Task.Status.COMPLETED:
                    raise TaskConflict(detail="Task is already completed.")
                if locked.status == Task.Status.RUNNING:
                    raise TaskInProgress()
                if locked.status == Task.Status.FAILED:
                    raise TaskConflict(
                        detail="Failed tasks must be retried via POST /api/v1/tasks/<id>/retry/."
                    )
                if locked.status == Task.Status.NEEDS_REVISION:
                    raise TaskConflict(
                        detail="Tasks awaiting revision must be retried via POST /api/v1/tasks/<id>/retry/."
                    )
                if locked.status not in (Task.Status.RECEIVED, Task.Status.QUEUED):
                    raise TaskConflict(detail="Task is not ready for execution.")
                # A QUEUED task with an APPROVED ApprovalRequest was async-approved —
                # skip the gate to avoid re-entering PENDING_APPROVAL.
                if locked.status == Task.Status.QUEUED:
                    if ApprovalRequest.objects.filter(
                        task=locked, status=ApprovalRequest.Status.APPROVED
                    ).exists():
                        skip_approval = True
            self._inject_governance_baseline(locked)
            locked.risk_tier = self._risk.classify(locked.input_text).value
            locked.error_detail = None

            if not skip_approval:
                # Check approval gate BEFORE committing to RUNNING. This ensures
                # run_attempt is only incremented when execution actually starts.
                ticket = ApprovalTicket(
                    ticket_id=str(uuid.uuid4()),
                    task_id=str(task.id),
                    summary=task.input_text[:200],
                    risk_tier=locked.risk_tier,
                )
                decision = self._gate.request(ticket)

                if decision == ApprovalDecision.PENDING:
                    locked.status = Task.Status.PENDING_APPROVAL
                    locked.save(
                        update_fields=[
                            "risk_tier",
                            "status",
                            "error_detail",
                            "metadata",
                            "updated_at",
                        ]
                    )
                    quorum = getattr(self._gate, "quorum", 1)
                    ApprovalRequest.objects.update_or_create(
                        task=locked,
                        defaults={
                            "ticket_id": ticket.ticket_id,
                            "risk_tier": locked.risk_tier,
                            "summary": ticket.summary,
                            "status": ApprovalRequest.Status.PENDING,
                            "decision_note": "",
                            "decided_at": None,
                            "quorum": quorum,
                        },
                    )
                    task.refresh_from_db()
                    logger.info(
                        "task_approval_pending task_id=%s risk=%s",
                        task.id,
                        task.risk_tier,
                    )
                    return task

                if decision == ApprovalDecision.REJECTED:
                    locked.status = Task.Status.FAILED
                    locked.error_code = APPROVAL_REJECTED
                    locked.error_detail = {
                        "code": APPROVAL_REJECTED,
                        "risk_tier": locked.risk_tier,
                    }
                    locked.save(
                        update_fields=[
                            "risk_tier",
                            "status",
                            "error_code",
                            "error_detail",
                            "metadata",
                            "updated_at",
                        ]
                    )
                    task.refresh_from_db()
                    logger.info(
                        "task_approval_rejected task_id=%s risk_tier=%s",
                        task.id,
                        task.risk_tier,
                    )
                    return task

            # APPROVED (or skip_approval=True) — commit to RUNNING (local pipeline or OpenClaw delegate).
            delegate_openclaw = bool(
                getattr(settings, "CLAWAGORA_OPENCLAW_DELEGATE_ENABLED", False)
                and self._openclaw_should_delegate(locked)
            )
            if delegate_openclaw:
                locked.run_attempt += 1
                locked.status = Task.Status.RUNNING
                md = dict(locked.metadata or {})
                oc = dict(md.get("openclaw") if isinstance(md.get("openclaw"), dict) else {})
                oc["phase"] = "delegating"
                md["openclaw"] = oc
                locked.metadata = md
                locked.save(
                    update_fields=[
                        "risk_tier",
                        "run_attempt",
                        "status",
                        "error_detail",
                        "metadata",
                        "updated_at",
                    ]
                )
            else:
                locked.run_attempt += 1
                locked.status = Task.Status.RUNNING
                locked.save(
                    update_fields=[
                        "risk_tier",
                        "run_attempt",
                        "status",
                        "error_detail",
                        "metadata",
                        "updated_at",
                    ]
                )

        task.refresh_from_db()
        if delegate_openclaw:
            logger.info(
                "task_openclaw_delegate_start task_id=%s risk=%s",
                task.id,
                task.risk_tier,
            )
            return self._post_openclaw_delegate_http(task)

        logger.info(
            "task_run_start risk=%s attempt=%s",
            task.risk_tier,
            task.run_attempt,
        )

        run_metadata = dict(task.metadata or {})
        merge_circuit_overrides_into_metadata(run_metadata)
        result = self._pipeline.run(
            task.input_text,
            run_metadata,
            request_id=str(task.id),
        )

        events: list[tuple[str, str, dict[str, Any]]] = []

        def append(phase: str, kind: str, payload: dict[str, Any]) -> None:
            events.append((phase, kind, payload))

        append(TaskPhase.INTAKE.value, "envelope", {"request_id": result.envelope.request_id})
        if result.classification:
            append(TaskPhase.CLASSIFY.value, "classification", result.classification.model_dump())
        if result.plan:
            append(TaskPhase.PLAN.value, "plan", result.plan.model_dump())
        for report in result.validation:
            append(TaskPhase.VALIDATE.value, report.validator_id, report.model_dump())

        if result.state == TaskState.FAILED:
            append(
                TaskPhase.TERMINAL.value,
                "failed",
                self._terminal_failed_payload(result),
            )
            try:
                self._persist_run(task, events, result, success=False)
            except Exception:
                logger.exception("persist_failed task_id=%s", task.id)
                self._force_failed_state(task, "persist_failed")
                raise
            record_prompt_circuit_outcome(result, success=False)
            logger.info("task_run_done status=%s error=%s", task.status, task.error_code)
            return task

        for art in result.artifacts:
            append(TaskPhase.EXECUTE.value, "artifact", art.model_dump())
        if result.synthesis:
            append(TaskPhase.SYNTHESIZE.value, "result", result.synthesis)
        append(TaskPhase.TERMINAL.value, "completed", {})

        try:
            self._persist_run(task, events, result, success=True)
        except Exception:
            logger.exception("persist_failed task_id=%s", task.id)
            self._force_failed_state(task, "persist_failed")
            raise
        record_prompt_circuit_outcome(result, success=True)
        logger.info("task_run_done status=%s", task.status)
        return task

    def inject_guidance(self, task: Task, guidance: str) -> Task:
        """Merge operator guidance into task metadata without changing execution state.

        Allowed for PENDING_APPROVAL, FAILED, and RECEIVED tasks. Guidance is
        appended to metadata["guidance_notes"] and visible to the pipeline on
        the next execution via task.metadata.
        """
        from django.utils import timezone

        _allowed = {
            Task.Status.PENDING_APPROVAL,
            Task.Status.FAILED,
            Task.Status.RECEIVED,
            Task.Status.NEEDS_REVISION,
        }
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            if locked.status not in _allowed:
                raise TaskConflict(
                    detail=f"Cannot inject guidance into a task with status '{locked.status}'."
                )
            metadata = dict(locked.metadata or {})
            notes = list(metadata.get("guidance_notes", []))
            notes.append({"note": guidance, "injected_at": timezone.now().isoformat()})
            metadata["guidance_notes"] = notes
            locked.metadata = metadata
            locked.save(update_fields=["metadata", "updated_at"])
        task.refresh_from_db()
        logger.info("task_guidance_injected task_id=%s", task.id)
        return task

    def retry_task(self, task: Task, *, async_execution: bool = False) -> Task:
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            if locked.status not in (Task.Status.FAILED, Task.Status.NEEDS_REVISION):
                raise TaskConflict(detail="Only failed or needs_revision tasks can be retried.")
            TaskEvent.objects.filter(task=locked).delete()
            Receipt.objects.filter(task=locked).delete()
            locked.status = Task.Status.QUEUED if async_execution else Task.Status.RECEIVED
            locked.error_code = ""
            locked.error_detail = None
            locked.classification = None
            locked.plan = None
            locked.validation_reports = None
            locked.external_ref = ""
            locked.save(
                update_fields=[
                    "status",
                    "error_code",
                    "error_detail",
                    "classification",
                    "plan",
                    "validation_reports",
                    "external_ref",
                    "updated_at",
                ]
            )
            # Clear stale approval data so the gate runs fresh on retry.
            ApprovalRequest.objects.filter(task=locked).delete()
        tid = str(task.id)
        if async_execution:
            try:
                enqueue_task_execution(tid)
            except Exception as exc:
                logger.warning("enqueue_failed task_id=%s error=%s", task.pk, exc)
                Task.objects.filter(pk=task.pk).update(
                    status=Task.Status.FAILED,
                    error_code=ENQUEUE_FAILED,
                    error_detail={
                        "code": ENQUEUE_FAILED,
                        "message": str(exc)[:2000],
                    },
                )
                raise
            return Task.objects.select_related("receipt").get(pk=task.pk)
        return self.run_task(Task.objects.get(pk=task.pk))

    def _terminal_failed_payload(self, result: PipelineResult) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_code": result.error or "failed",
            "stage": self._failure_stage(result),
        }
        if result.error_type:
            payload["error_type"] = result.error_type
        return payload

    def _failure_stage(self, result: PipelineResult) -> str:
        # error_stage is set by the pipeline for both normal validation failures
        # and unexpected exceptions, so this is the authoritative source.
        if result.error_stage:
            return result.error_stage
        return TaskPhase.EXECUTE.value

    def _persist_run(
        self,
        task: Task,
        events: list[tuple[str, str, dict[str, Any]]],
        result: PipelineResult,
        *,
        success: bool,
    ) -> None:
        with transaction.atomic():
            TaskEvent.objects.filter(task=task).delete()
            bulk = [
                TaskEvent(
                    task=task,
                    sequence=i,
                    phase=phase,
                    kind=kind,
                    payload=payload,
                )
                for i, (phase, kind, payload) in enumerate(events, start=1)
            ]
            batch_size = 500
            TaskEvent.objects.bulk_create(bulk, batch_size=batch_size)

            task.external_ref = result.envelope.request_id
            task.classification = (
                result.classification.model_dump() if result.classification else None
            )
            task.plan = result.plan.model_dump() if result.plan else None
            task.validation_reports = [r.model_dump() for r in result.validation]
            feedback = accountability_feedback_from_result(result, success=success)
            loop_snapshot: dict[str, Any] | None = None
            prompt_trace = self._prompt_trace_from_result(result)
            if feedback:
                task.metadata = merge_accountability_feedback(task.metadata or {}, feedback)
                loop_snapshot = governance_loop_snapshot(task.metadata, feedback)
            if loop_snapshot and prompt_trace:
                loop_snapshot["prompt_trace"] = prompt_trace

            if success:
                if not result.synthesis:
                    logger.error("pipeline_invariant_failed task_id=%s", task.id)
                    Receipt.objects.filter(task=task).delete()
                    task.status = Task.Status.FAILED
                    task.error_code = PIPELINE_INVARIANT_FAILED
                    task.error_detail = {"code": MISSING_SYNTHESIS}
                else:
                    body = self._build_receipt_body(result)
                    if loop_snapshot:
                        body["governance_loop"] = loop_snapshot
                    if prompt_trace:
                        body["prompt_trace"] = prompt_trace
                    body_hash = hash_body(body)
                    Receipt.objects.update_or_create(
                        task=task,
                        defaults={"body": body, "body_hash": body_hash},
                    )
                    task.status = Task.Status.COMPLETED
                    task.error_code = ""
                    task.error_detail = None
            else:
                Receipt.objects.filter(task=task).delete()
                task.status = Task.Status.FAILED
                task.error_code = result.error or "failed"
                task.error_detail = self._error_detail_for_failure(result)
                if result.error:
                    logger.warning(
                        "task_failed task_id=%s error=%s error_type=%s",
                        task.id,
                        result.error,
                        result.error_type,
                    )

            task.save()
            if loop_snapshot or prompt_trace:
                payload: dict[str, Any] = loop_snapshot or {}
                if prompt_trace:
                    payload["prompt_trace"] = prompt_trace
                TaskEvent.objects.create(
                    task=task,
                    sequence=len(events) + 1,
                    phase=TaskPhase.GOVERNANCE.value,
                    kind="accountability_feedback",
                    payload=payload,
                )

    def submit_governance_feedback(
        self,
        task: Task,
        entries: list[dict[str, Any]],
        *,
        source: str = "operator",
    ) -> Task:
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            merged_metadata = merge_accountability_feedback(locked.metadata or {}, entries)
            snapshot = governance_loop_snapshot(merged_metadata, entries)
            next_seq = (
                TaskEvent.objects.filter(task=locked).aggregate(max_seq=Max("sequence"))["max_seq"]
                or 0
            ) + 1
            TaskEvent.objects.create(
                task=locked,
                sequence=next_seq,
                phase=TaskPhase.GOVERNANCE.value,
                kind="manual_feedback",
                payload={
                    "source": source,
                    "entries": entries,
                    "loop": snapshot,
                },
            )
            locked.metadata = merged_metadata
            locked.save(update_fields=["metadata", "updated_at"])
        return (
            Task.objects.select_related("receipt", "approval_request")
            .prefetch_related("approval_request__votes")
            .get(pk=task.pk)
        )

    def _inject_governance_baseline(self, task: Task) -> None:
        metadata = dict(task.metadata or {})
        profile = str(metadata.get("governance_profile") or "").strip().lower()
        if not profile:
            return
        state = GovernanceProfileState.objects.filter(profile=profile).first()
        if not state or not isinstance(state.baseline_weights, dict):
            return
        metadata["governance_baseline_weights"] = state.baseline_weights
        task.metadata = metadata

    def _error_detail_for_failure(self, result: PipelineResult) -> dict[str, Any] | None:
        if not result.error and not result.error_type:
            return None
        out: dict[str, Any] = {"code": result.error or "failed"}
        if result.error_type:
            out["error_type"] = result.error_type
        return out

    def _build_receipt_body(self, result: PipelineResult) -> dict[str, Any]:
        """Augment the kernel synthesis with trust, optimisation, and rollback data.

        Adds three keys to the receipt body:
          trust_score     – TrustScore from classification confidence + validation.
          optimization    – OptimizationReport with actionable recommendations.
          rollback_plan   – RollbackPlan built from completed execution artifacts.

        The kernel synthesis dict is never mutated; a new dict is returned.
        """
        body: dict[str, Any] = dict(result.synthesis or {})

        # Trust score — requires classification; skipped when classification is absent.
        if result.classification is not None:
            trust = self._trust.compute(result.classification, result.validation)
            body["trust_score"] = trust.model_dump()

        # Optimisation recommendations — always generated.
        opt = self._opt.analyze(
            task_id=result.envelope.request_id,
            classification=result.classification,
            validation=result.validation,
            artifact_count=len(result.artifacts),
        )
        body["optimization"] = opt.model_dump()

        # Rollback plan — empty steps when no artifacts (e.g. short-circuit failure).
        body["rollback_plan"] = build_rollback_plan(
            result.envelope.request_id, result.artifacts
        ).model_dump()

        return body

    def _prompt_trace_from_result(self, result: PipelineResult) -> dict[str, Any] | None:
        trace = (result.envelope.metadata or {}).get("prompt_trace")
        return trace if isinstance(trace, dict) and trace else None

    def _openclaw_should_delegate(self, locked: Task) -> bool:
        if not getattr(settings, "CLAWAGORA_OPENCLAW_DELEGATE_ENABLED", False):
            return False
        oc = (locked.metadata or {}).get("openclaw")
        if not isinstance(oc, dict):
            return False
        return oc.get("delegate") is True

    def _post_openclaw_delegate_http(self, task: Task) -> Task:
        from orchestration.openclaw_delegate import (
            build_callback_url,
            build_delegate_payload,
            post_delegate,
            resolve_agent_ids,
        )

        url = (getattr(settings, "CLAWAGORA_OPENCLAW_DELEGATE_URL", "") or "").strip()
        if not url:
            Task.objects.filter(pk=task.pk).update(
                status=Task.Status.FAILED,
                error_code=OPENCLAW_DELEGATE_FAILED,
                error_detail={
                    "code": OPENCLAW_DELEGATE_FAILED,
                    "reason": "missing_CLAWAGORA_OPENCLAW_DELEGATE_URL",
                },
            )
            return Task.objects.select_related("receipt", "approval_request").get(pk=task.pk)
        agents = resolve_agent_ids(
            metadata=dict(task.metadata or {}),
            risk_tier=task.risk_tier,
            config_json=getattr(settings, "CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON", ""),
        )
        cb = build_callback_url(getattr(settings, "CLAWAGORA_PUBLIC_BASE_URL", "") or "")
        payload = build_delegate_payload(
            task_id=str(task.id),
            input_text=task.input_text,
            metadata=dict(task.metadata or {}),
            risk_tier=task.risk_tier,
            agents=agents,
            callback_url=cb,
        )
        ok, http_status, detail = post_delegate(
            url=url,
            payload=payload,
            api_key=getattr(settings, "CLAWAGORA_OPENCLAW_API_KEY", ""),
            timeout_sec=float(getattr(settings, "CLAWAGORA_OPENCLAW_DELEGATE_TIMEOUT_SEC", 60.0)),
        )
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            md = dict(locked.metadata or {})
            oc = dict(md.get("openclaw") if isinstance(md.get("openclaw"), dict) else {})
            if ok:
                oc["phase"] = "awaiting_callback"
                oc["delegate_http_status"] = http_status
            else:
                oc["phase"] = "delegate_failed"
                oc["delegate_error"] = detail[:2000]
            md["openclaw"] = oc
            locked.metadata = md
            if ok:
                locked.save(update_fields=["metadata", "updated_at"])
            else:
                locked.status = Task.Status.FAILED
                locked.error_code = OPENCLAW_DELEGATE_FAILED
                locked.error_detail = {
                    "code": OPENCLAW_DELEGATE_FAILED,
                    "http_status": http_status,
                    "detail": detail[:2000],
                }
                locked.save(
                    update_fields=[
                        "metadata",
                        "status",
                        "error_code",
                        "error_detail",
                        "updated_at",
                    ]
                )
        return Task.objects.select_related("receipt", "approval_request").get(pk=task.pk)

    def apply_openclaw_callback(self, payload: dict[str, Any]) -> Task:
        from django.http import Http404
        from django.utils import timezone

        task_id = str(payload.get("task_id") or "")
        if not task_id:
            raise TaskConflict(detail="task_id is required.")
        st = str(payload.get("status") or "").lower()
        if st not in ("completed", "failed"):
            raise TaskConflict(detail="status must be completed or failed.")
        ext_id = str(payload.get("external_id") or "").strip()
        with transaction.atomic():
            locked = Task.objects.select_for_update().filter(pk=task_id).first()
            if not locked:
                raise Http404()
            oc_existing = (locked.metadata or {}).get("openclaw")
            if (
                locked.status in (Task.Status.COMPLETED, Task.Status.FAILED)
                and isinstance(oc_existing, dict)
                and oc_existing.get("phase") == "callback_received"
            ):
                existing_ext = str(oc_existing.get("external_id") or "").strip()
                if ext_id and existing_ext and existing_ext == ext_id:
                    return Task.objects.select_related("receipt", "approval_request").get(pk=task_id)
            if locked.status != Task.Status.RUNNING:
                raise TaskConflict(detail="Task is not in running state.")
            oc = (locked.metadata or {}).get("openclaw")
            if not isinstance(oc, dict) or oc.get("phase") != "awaiting_callback":
                raise TaskConflict(detail="Task is not awaiting OpenClaw callback.")
            md = dict(locked.metadata or {})
            oc2 = dict(oc)
            oc2["phase"] = "callback_received"
            oc2["callback_at"] = timezone.now().isoformat()
            if ext_id:
                oc2["external_id"] = ext_id
            from orchestration.openclaw_callback_artifacts import (
                OPENCLAW_CALLBACK_SCHEMA,
                normalize_openclaw_callback_artifacts,
            )

            artifacts, art_err = normalize_openclaw_callback_artifacts(payload.get("artifacts"))
            if art_err:
                raise TaskConflict(detail=art_err)
            oc2["callback_schema"] = OPENCLAW_CALLBACK_SCHEMA
            oc2["artifacts"] = artifacts
            md["openclaw"] = oc2
            locked.metadata = md
            if st == "failed":
                locked.status = Task.Status.FAILED
                locked.error_code = str(payload.get("error_code") or "openclaw_failed")
                locked.error_detail = {
                    "code": locked.error_code,
                    "detail": (payload.get("error") or "")[:2000],
                }
                locked.save(
                    update_fields=[
                        "metadata",
                        "status",
                        "error_code",
                        "error_detail",
                        "updated_at",
                    ]
                )
                return Task.objects.select_related("receipt", "approval_request").get(pk=task_id)
            synthesis = payload.get("synthesis")
            if not isinstance(synthesis, dict):
                raise TaskConflict(detail="synthesis must be a JSON object when status is completed.")
            body: dict[str, Any] = dict(synthesis)
            body["source"] = "openclaw"
            body["openclaw_bridge"] = {
                "agents": payload.get("agents"),
                "external_id": payload.get("external_id"),
            }
            body["openclaw_artifacts"] = artifacts
            body_hash = hash_body(body)
            Receipt.objects.update_or_create(
                task=locked,
                defaults={"body": body, "body_hash": body_hash},
            )
            TaskEvent.objects.filter(task=locked).delete()
            TaskEvent.objects.create(
                task=locked,
                sequence=1,
                phase=TaskPhase.TERMINAL.value,
                kind="openclaw_completed",
                payload={
                    "source": "openclaw_callback",
                    "artifact_count": len(artifacts),
                    "artifact_roles": [a.get("role", "") for a in artifacts[:24]],
                },
            )
            locked.status = Task.Status.COMPLETED
            locked.error_code = ""
            locked.error_detail = None
            locked.external_ref = str(locked.id)
            locked.save(
                update_fields=[
                    "metadata",
                    "status",
                    "error_code",
                    "error_detail",
                    "external_ref",
                    "updated_at",
                ]
            )
        return Task.objects.select_related("receipt", "approval_request").get(pk=task_id)

    def _force_failed_state(self, task: Task, code: str) -> None:
        with transaction.atomic():
            locked = Task.objects.select_for_update().get(pk=task.pk)
            if locked.status == Task.Status.RUNNING:
                locked.status = Task.Status.FAILED
                locked.error_code = code
                locked.error_detail = {"code": code}
                locked.save(update_fields=["status", "error_code", "error_detail", "updated_at"])


_svc: OrchestrationService | None = None


def get_orchestration_service() -> OrchestrationService:
    global _svc
    if _svc is None:
        _svc = OrchestrationService()
    return _svc


def set_orchestration_service(svc: OrchestrationService) -> None:
    """Replace the singleton with a pre-configured instance (useful in tests)."""
    global _svc
    _svc = svc


def reset_orchestration_service() -> None:
    global _svc
    _svc = None

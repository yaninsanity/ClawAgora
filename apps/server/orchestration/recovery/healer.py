from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from orchestration.app_settings import heal_config, is_rq_stack_active
from orchestration.error_codes import (
    APPROVAL_TIMEOUT,
    STALE_QUEUED_REQUEUE_FAILED,
    STALE_QUEUED_TIMEOUT,
    STALE_RUNNING_TIMEOUT,
)
from orchestration.models import ApprovalRequest, Task

logger = logging.getLogger(__name__)


@dataclass
class StaleTaskHealResult:
    running_marked_failed: int = 0
    queued_marked_failed: int = 0
    queued_re_enqueued: int = 0
    pending_approval_expired: int = 0
    task_ids_running: list[str] = field(default_factory=list)
    task_ids_queued_failed: list[str] = field(default_factory=list)
    task_ids_queued_requeued: list[str] = field(default_factory=list)
    task_ids_approval_expired: list[str] = field(default_factory=list)


def heal_stale_tasks(*, dry_run: bool = False) -> StaleTaskHealResult:
    cfg = heal_config()
    if not cfg.enabled:
        return StaleTaskHealResult()

    now = timezone.now()
    r_sec = cfg.stale_running_seconds
    q_sec = cfg.stale_queued_seconds
    requeue = cfg.requeue_stale_queued

    running_cutoff = now - timedelta(seconds=r_sec)
    queued_cutoff = now - timedelta(seconds=q_sec)
    out = StaleTaskHealResult()

    running_qs = Task.objects.filter(
        status=Task.Status.RUNNING,
        updated_at__lt=running_cutoff,
    )
    out.task_ids_running = [str(x) for x in running_qs.values_list("id", flat=True)]

    queued_qs = Task.objects.filter(
        status=Task.Status.QUEUED,
        updated_at__lt=queued_cutoff,
    )
    queued_ids_requeue: list[str] = []
    queued_ids_fail: list[str] = []
    if requeue and is_rq_stack_active():
        queued_ids_requeue = [str(x) for x in queued_qs.values_list("id", flat=True)]
    else:
        queued_ids_fail = [str(x) for x in queued_qs.values_list("id", flat=True)]

    if dry_run:
        out.running_marked_failed = len(out.task_ids_running)
        out.queued_marked_failed = len(queued_ids_fail)
        out.queued_re_enqueued = len(queued_ids_requeue)
        out.task_ids_queued_failed = list(queued_ids_fail)
        out.task_ids_queued_requeued = list(queued_ids_requeue)
        if cfg.expire_pending_approval and cfg.stale_pending_approval_seconds:
            pa_cutoff = now - timedelta(seconds=cfg.stale_pending_approval_seconds)
            pa_ids = list(
                Task.objects.filter(
                    status=Task.Status.PENDING_APPROVAL,
                    updated_at__lt=pa_cutoff,
                ).values_list("id", flat=True)
            )
            out.task_ids_approval_expired = [str(x) for x in pa_ids]
            out.pending_approval_expired = len(pa_ids)
        return out

    if out.task_ids_running:
        detail = {"code": STALE_RUNNING_TIMEOUT, "cutoff_seconds": r_sec}
        with transaction.atomic():
            updated = Task.objects.filter(
                id__in=out.task_ids_running,
                status=Task.Status.RUNNING,
            ).update(
                status=Task.Status.FAILED,
                error_code=STALE_RUNNING_TIMEOUT,
                error_detail=detail,
            )
        out.running_marked_failed = updated
        logger.warning(
            "heal_stale_running updated=%s cutoff_s=%s",
            updated,
            r_sec,
        )

    if queued_ids_fail:
        detail = {"code": STALE_QUEUED_TIMEOUT, "cutoff_seconds": q_sec}
        with transaction.atomic():
            updated = Task.objects.filter(
                id__in=queued_ids_fail,
                status=Task.Status.QUEUED,
            ).update(
                status=Task.Status.FAILED,
                error_code=STALE_QUEUED_TIMEOUT,
                error_detail=detail,
            )
        out.queued_marked_failed = updated
        out.task_ids_queued_failed = queued_ids_fail
        logger.warning(
            "heal_stale_queued_failed updated=%s cutoff_s=%s",
            updated,
            q_sec,
        )

    if queued_ids_requeue:
        from orchestration.queue import enqueue_task_execution

        ok: list[str] = []
        for tid in queued_ids_requeue:
            try:
                enqueue_task_execution(tid)
                ok.append(tid)
            except Exception as exc:
                logger.warning("heal_requeue_failed task_id=%s error=%s", tid, exc)
                Task.objects.filter(pk=tid, status=Task.Status.QUEUED).update(
                    status=Task.Status.FAILED,
                    error_code=STALE_QUEUED_REQUEUE_FAILED,
                    error_detail={
                        "code": STALE_QUEUED_REQUEUE_FAILED,
                        "message": str(exc)[:2000],
                    },
                )
        out.queued_re_enqueued = len(ok)
        out.task_ids_queued_requeued = ok
        if ok:
            logger.info("heal_requeued count=%s", len(ok))

    # Auto-reject stale PENDING_APPROVAL tasks.
    if cfg.expire_pending_approval and cfg.stale_pending_approval_seconds:
        pa_sec = cfg.stale_pending_approval_seconds
        pa_cutoff = now - timedelta(seconds=pa_sec)
        pa_qs = Task.objects.filter(
            status=Task.Status.PENDING_APPROVAL,
            updated_at__lt=pa_cutoff,
        )
        pa_ids = [str(x) for x in pa_qs.values_list("id", flat=True)]
        if pa_ids:
            detail = {"code": APPROVAL_TIMEOUT, "cutoff_seconds": pa_sec}
            with transaction.atomic():
                updated = Task.objects.filter(
                    id__in=pa_ids,
                    status=Task.Status.PENDING_APPROVAL,
                ).update(
                    status=Task.Status.FAILED,
                    error_code=APPROVAL_TIMEOUT,
                    error_detail=detail,
                )
                ApprovalRequest.objects.filter(
                    task_id__in=pa_ids,
                    status=ApprovalRequest.Status.PENDING,
                ).update(
                    status=ApprovalRequest.Status.REJECTED,
                    decision_note=f"Auto-rejected: approval window exceeded {pa_sec}s.",
                    decided_at=now,
                )
            out.pending_approval_expired = updated
            out.task_ids_approval_expired = pa_ids
            logger.warning(
                "heal_approval_expired updated=%s cutoff_s=%s",
                updated,
                pa_sec,
            )

    return out

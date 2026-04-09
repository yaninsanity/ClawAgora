from __future__ import annotations

import logging

from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def enqueue_task_execution(task_id: str) -> str:
    try:
        from django_rq import get_queue
    except ImportError as exc:
        raise ImproperlyConfigured(
            "Async execution requires optional dependencies. Install with: pip install clawagora[async]"
        ) from exc

    queue = get_queue("clawagora")
    from orchestration.jobs import run_task_job

    job = queue.enqueue(run_task_job, task_id)
    logger.info("task_enqueued task_id=%s job_id=%s", task_id, job.id)
    return job.id

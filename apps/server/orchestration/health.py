from __future__ import annotations

from django.db import connection
from django.http import JsonResponse

from orchestration.app_settings import is_rq_stack_active


def health(_request):
    payload: dict = {"status": "ok", "database": "ok"}

    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse(
            {"status": "unhealthy", "database": "unavailable"},
            status=503,
        )

    if not is_rq_stack_active():
        payload["redis"] = "skipped"
        payload["queue"] = None
        return JsonResponse(payload)

    try:
        from django_rq import get_queue

        q = get_queue("clawagora")
        conn = q.connection
        conn.ping()

        payload["redis"] = "ok"
        payload["queue"] = {
            "name": "clawagora",
            "queued_jobs": len(q),
            "started_jobs": q.started_job_registry.get_job_count(cleanup=False),
            "deferred_jobs": q.deferred_job_registry.get_job_count(cleanup=False),
        }
    except Exception as exc:
        payload["redis"] = "unavailable"
        payload["redis_error"] = str(exc)[:200]
        payload["queue"] = None

    return JsonResponse(payload)

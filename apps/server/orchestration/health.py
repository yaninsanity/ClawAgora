from __future__ import annotations

import os

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

from clawagora.version import __version__ as clawagora_version
from orchestration.app_settings import is_rq_stack_active


def health(_request):
    git_sha = (os.environ.get("GIT_SHA") or os.environ.get("SOURCE_COMMIT") or "").strip()[:40]
    cache_url = (getattr(settings, "CLAWAGORA_CACHE_URL", "") or "").strip()
    cache_backend = (
        "redis"
        if cache_url
        else "locmem"
    )
    payload: dict = {
        "status": "ok",
        "version": clawagora_version,
        "git_sha": git_sha or None,
        "database": "ok",
        "cache": {
            "backend": cache_backend,
            "shared": bool(cache_url),
            "status": "unknown",
        },
    }

    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse(
            {"status": "unhealthy", "database": "unavailable"},
            status=503,
        )

    try:
        probe_key = "health:cache_probe"
        cache.set(probe_key, "1", timeout=5)
        payload["cache"]["status"] = "ok" if cache.get(probe_key) == "1" else "unavailable"
    except Exception as exc:
        payload["cache"]["status"] = "unavailable"
        payload["cache"]["error"] = str(exc)[:200]

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

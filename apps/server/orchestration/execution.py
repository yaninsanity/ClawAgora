from __future__ import annotations

from rest_framework.exceptions import ValidationError

from orchestration.app_settings import ExecutionMode, default_execution_mode


def resolve_execution_mode(request) -> ExecutionMode:
    raw = (request.headers.get("X-ClawAgora-Execution") or "").strip()
    if not raw:
        return default_execution_mode()
    header = raw.lower()
    if header == "async":
        return "async"
    if header == "sync":
        return "sync"
    raise ValidationError(
        {"X-ClawAgora-Execution": "Must be 'sync' or 'async'."},
        code="invalid_execution_mode",
    )

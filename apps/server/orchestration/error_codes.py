from __future__ import annotations

from dataclasses import dataclass
from rest_framework import status


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    code: str
    message: str
    http_status: int


# API-layer error taxonomy (stable external contract).
TASK_CONFLICT = ErrorSpec(
    code="task_conflict",
    message="The task cannot be executed in its current state.",
    http_status=status.HTTP_409_CONFLICT,
)
TASK_IN_PROGRESS = ErrorSpec(
    code="task_in_progress",
    message="Task execution is already in progress.",
    http_status=status.HTTP_409_CONFLICT,
)
NOT_FOUND = ErrorSpec(
    code="not_found",
    message="Resource was not found.",
    http_status=status.HTTP_404_NOT_FOUND,
)
PERMISSION_DENIED = ErrorSpec(
    code="permission_denied",
    message="Permission denied.",
    http_status=status.HTTP_403_FORBIDDEN,
)
UNKNOWN_ERROR = ErrorSpec(
    code="error",
    message="Unexpected error.",
    http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
)


# Task lifecycle / recovery error codes (persisted on Task.error_code).
ENQUEUE_FAILED = "enqueue_failed"
CANCELLED = "cancelled"
STALE_RUNNING_TIMEOUT = "stale_running_timeout"
STALE_QUEUED_TIMEOUT = "stale_queued_timeout"
STALE_QUEUED_REQUEUE_FAILED = "stale_queued_requeue_failed"
APPROVAL_TIMEOUT = "approval_timeout"
APPROVAL_REJECTED = "approval_rejected"
PIPELINE_INVARIANT_FAILED = "pipeline_invariant_failed"
MISSING_SYNTHESIS = "missing_synthesis"
OPENCLAW_DELEGATE_FAILED = "openclaw_delegate_failed"
OPENCLAW_CALLBACK_INVALID = "openclaw_callback_invalid"

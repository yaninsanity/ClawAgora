from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

from orchestration.error_codes import (
    NOT_FOUND,
    PERMISSION_DENIED,
    TASK_CONFLICT,
    TASK_IN_PROGRESS,
    UNKNOWN_ERROR,
)


class TaskConflict(APIException):
    status_code = TASK_CONFLICT.http_status
    default_detail = TASK_CONFLICT.message
    default_code = TASK_CONFLICT.code


class TaskInProgress(APIException):
    status_code = TASK_IN_PROGRESS.http_status
    default_detail = TASK_IN_PROGRESS.message
    default_code = TASK_IN_PROGRESS.code


def envelope_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return response
    if isinstance(exc, Http404):
        code = NOT_FOUND.code
    elif isinstance(exc, PermissionDenied):
        code = PERMISSION_DENIED.code
    else:
        code = getattr(exc, "default_code", None) or UNKNOWN_ERROR.code
    payload = {
        "status": response.status_code,
        "code": code,
        "body": response.data,
    }
    response.data = payload
    return response

from __future__ import annotations

import contextvars
import json
import logging
import traceback

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "clawagora_request_id", default=None
)
task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "clawagora_task_id", default=None
)


def bind_task_context(task_id: str | None):
    return task_id_var.set(task_id)


def reset_task_context(token: contextvars.Token) -> None:
    task_id_var.reset(token)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rid = request_id_var.get()
        tid = task_id_var.get()
        d = record.__dict__
        if "request_id" not in d:
            d["request_id"] = "-" if rid is None else str(rid)
        if "task_id" not in d:
            d["task_id"] = "-" if tid is None else str(tid)
        return True


def _record_str(d: dict, key: str, default: str = "-") -> str:
    v = d.get(key, default)
    return default if v is None else str(v)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = record.__dict__
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _record_str(d, "request_id"),
            "task_id": _record_str(d, "task_id"),
        }
        if record.exc_info:
            payload["traceback"] = "".join(traceback.format_exception(*record.exc_info)).strip()
        return json.dumps(payload, ensure_ascii=False)

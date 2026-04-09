from __future__ import annotations

from typing import Any


def build_logging_dict(*, log_level: str, log_format: str) -> dict[str, Any]:
    use_json = log_format.strip().lower() == "json"
    formatter = "json" if use_json else "plain"
    formatters = {
        "plain": {
            "format": "%(levelname)s %(name)s [request_id=%(request_id)s task_id=%(task_id)s] %(message)s",
        },
        "json": {"()": "orchestration.logging_support.JsonFormatter"},
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "orchestration_context": {
                "()": "orchestration.logging_support.RequestContextFilter",
            },
        },
        "formatters": formatters,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": formatter,
                "filters": ["orchestration_context"],
            },
        },
        "root": {
            "handlers": ["console"],
            "level": log_level,
        },
        "loggers": {
            "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            "orchestration": {"handlers": ["console"], "level": log_level, "propagate": False},
            "clawagora": {"handlers": ["console"], "level": log_level, "propagate": False},
        },
    }

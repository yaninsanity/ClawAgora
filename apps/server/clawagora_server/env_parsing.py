"""Environment value parsing for Django settings (fail-fast, testable)."""

from __future__ import annotations

import logging

from django.core.exceptions import ImproperlyConfigured


def parse_execution_mode(raw: str | None) -> str:
    value = (raw or "sync").strip().lower()
    if value not in ("sync", "async"):
        raise ImproperlyConfigured(
            f"CLAWAGORA_EXECUTION_MODE must be 'sync' or 'async', got {raw!r}"
        )
    return value


def parse_positive_int(
    setting_name: str,
    raw: str | None,
    default: int,
    *,
    minimum: int = 1,
) -> int:
    if raw is None or str(raw).strip() == "":
        candidate = default
    else:
        try:
            candidate = int(str(raw).strip(), 10)
        except ValueError as exc:
            raise ImproperlyConfigured(
                f"{setting_name} must be a base-10 integer, got {raw!r}"
            ) from exc
    if candidate < minimum:
        raise ImproperlyConfigured(f"{setting_name} must be >= {minimum}, got {candidate}")
    return candidate


def parse_log_level(raw: str | None, default: str = "INFO") -> str:
    name = (raw or default).strip().upper()
    if not name:
        name = default.strip().upper()
    if name not in logging.getLevelNamesMapping():
        allowed = ", ".join(sorted(logging.getLevelNamesMapping()))
        raise ImproperlyConfigured(
            f"LOG_LEVEL must be a Python logging level name ({allowed}), got {raw!r}"
        )
    return name


def parse_log_format(raw: str | None, default: str = "text") -> str:
    value = (raw or default).strip().lower()
    if not value:
        value = default.strip().lower()
    if value not in ("text", "json"):
        raise ImproperlyConfigured(f"LOG_FORMAT must be 'text' or 'json', got {raw!r}")
    return value


def parse_non_negative_float(
    setting_name: str,
    raw: str | None,
    default: float,
) -> float:
    if raw is None or str(raw).strip() == "":
        candidate = default
    else:
        try:
            candidate = float(str(raw).strip())
        except ValueError as exc:
            raise ImproperlyConfigured(f"{setting_name} must be a float, got {raw!r}") from exc
    if candidate < 0:
        raise ImproperlyConfigured(f"{setting_name} must be >= 0, got {candidate}")
    return candidate

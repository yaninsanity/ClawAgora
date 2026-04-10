"""Optional task metadata for cross-run correlation and external memory references.

Bridges receive the same data inside ``metadata["clawagora_context"]`` and, for convenience,
as a top-level ``context`` object on the OpenClaw delegate POST body.
"""

from __future__ import annotations

from typing import Any

CLAWAGORA_CONTEXT_KEY = "clawagora_context"

MAX_SESSION_ID_LEN = 256
MAX_CORRELATION_ID_LEN = 128
MAX_MEMORY_REFS = 32
MAX_MEMORY_REF_LEN = 256


def validate_clawagora_context(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("clawagora_context must be an object.")
    allowed = {"session_id", "correlation_id", "memory_refs"}
    extras = set(raw.keys()) - allowed
    if extras:
        raise ValueError("Unknown keys in clawagora_context: " + ", ".join(sorted(extras)))

    out: dict[str, Any] = {}

    sid = raw.get("session_id")
    if sid is not None:
        if not isinstance(sid, str):
            raise ValueError("session_id must be a string.")
        sid = sid.strip()
        if len(sid) > MAX_SESSION_ID_LEN:
            raise ValueError("session_id is too long.")
        if sid:
            out["session_id"] = sid

    corr = raw.get("correlation_id")
    if corr is not None:
        if not isinstance(corr, str):
            raise ValueError("correlation_id must be a string.")
        corr = corr.strip()
        if len(corr) > MAX_CORRELATION_ID_LEN:
            raise ValueError("correlation_id is too long.")
        if corr:
            out["correlation_id"] = corr

    refs = raw.get("memory_refs")
    if refs is not None:
        if not isinstance(refs, list):
            raise ValueError("memory_refs must be an array of strings.")
        if len(refs) > MAX_MEMORY_REFS:
            raise ValueError("Too many memory_refs entries.")
        cleaned: list[str] = []
        for x in refs:
            if not isinstance(x, str):
                raise ValueError("memory_refs must be an array of strings.")
            t = x.strip()
            if not t:
                continue
            if len(t) > MAX_MEMORY_REF_LEN:
                raise ValueError("A memory_refs entry is too long.")
            cleaned.append(t)
        if cleaned:
            out["memory_refs"] = cleaned

    return out


def normalize_task_metadata_clawagora_context(value: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``value`` with ``clawagora_context`` validated and trimmed."""
    from rest_framework.serializers import ValidationError

    if CLAWAGORA_CONTEXT_KEY not in value:
        return value
    try:
        normalized = validate_clawagora_context(value[CLAWAGORA_CONTEXT_KEY])
    except ValueError as e:
        raise ValidationError({CLAWAGORA_CONTEXT_KEY: [str(e)]}) from e
    new_val = dict(value)
    if not normalized:
        new_val.pop(CLAWAGORA_CONTEXT_KEY, None)
    else:
        new_val[CLAWAGORA_CONTEXT_KEY] = normalized
    return new_val


def merge_patch_task_metadata(base: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge patch into base; deep-merge dict values for ``clawagora_context`` and ``openclaw``."""
    b = dict(base or {})
    out = dict(b)
    for k, v in patch.items():
        if k in ("clawagora_context", "openclaw") and isinstance(v, dict):
            prev = b.get(k)
            if isinstance(prev, dict):
                out[k] = {**prev, **v}
            else:
                out[k] = dict(v)
        else:
            out[k] = v
    return out


def assert_task_metadata_within_limits(value: dict[str, Any]) -> None:
    """Raise ``rest_framework.serializers.ValidationError`` if serialized size or key count exceeds settings."""
    import json

    from django.conf import settings
    from rest_framework.serializers import ValidationError

    raw = json.dumps(value, ensure_ascii=False)
    if len(raw) > settings.CLAWAGORA_MAX_METADATA_BYTES:
        raise ValidationError("Metadata payload is too large.")
    if len(value) > settings.CLAWAGORA_MAX_METADATA_KEYS:
        raise ValidationError("Too many metadata keys.")


def extract_delegate_context_bundle(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Build the delegate payload ``context`` field from stored task metadata."""
    ctx = metadata.get(CLAWAGORA_CONTEXT_KEY)
    if not isinstance(ctx, dict) or not ctx:
        return None
    out: dict[str, Any] = {}
    sid = ctx.get("session_id")
    if isinstance(sid, str) and sid.strip():
        out["session_id"] = sid.strip()
    corr = ctx.get("correlation_id")
    if isinstance(corr, str) and corr.strip():
        out["correlation_id"] = corr.strip()
    refs = ctx.get("memory_refs")
    if isinstance(refs, list):
        safe = [str(x).strip() for x in refs if isinstance(x, str) and str(x).strip()]
        if safe:
            out["memory_refs"] = safe[:MAX_MEMORY_REFS]
    return out or None

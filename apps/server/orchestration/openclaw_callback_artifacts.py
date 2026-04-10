"""Optional multi-agent artifacts on OpenClaw callback bodies (clawagora.openclaw.callback.v1).

Bridges may attach an ``artifacts`` array so ClawAgora can surface proposer/critic/reviewer
outputs in metadata, receipts, and timeline without running those agents inside the kernel.
"""

from __future__ import annotations

from typing import Any

MAX_ARTIFACTS = 32
MAX_ROLE_LEN = 64
MAX_AGENT_ID_LEN = 128
MAX_CONTENT_CHARS = 12_000
MAX_META_KEYS = 12
MAX_META_STR_LEN = 512

OPENCLAW_CALLBACK_SCHEMA = "clawagora.openclaw.callback.v1"


def normalize_openclaw_callback_artifacts(raw: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Return (sanitized_artifacts, error_message). Empty list if *raw* is None."""
    if raw is None:
        return ([], None)
    if not isinstance(raw, list):
        return ([], "artifacts must be a JSON array when present.")
    out: list[dict[str, Any]] = []
    for item in raw[:MAX_ARTIFACTS]:
        if not isinstance(item, dict):
            return ([], "each artifact must be a JSON object.")
        role = str(item.get("role") or "agent").strip()[:MAX_ROLE_LEN] or "agent"
        text = item.get("content")
        if text is None:
            text = item.get("text")
        if text is None:
            content = ""
        elif isinstance(text, str):
            content = text.strip()[:MAX_CONTENT_CHARS]
        else:
            content = str(text).strip()[:MAX_CONTENT_CHARS]
        agent_raw = item.get("agent_id")
        agent_id = (
            str(agent_raw).strip()[:MAX_AGENT_ID_LEN]
            if agent_raw is not None and str(agent_raw).strip()
            else ""
        )
        row: dict[str, Any] = {"role": role, "content": content}
        if agent_id:
            row["agent_id"] = agent_id
        meta_in = item.get("meta")
        if isinstance(meta_in, dict) and meta_in:
            meta_out: dict[str, str] = {}
            for k, v in list(meta_in.items())[:MAX_META_KEYS]:
                ks = str(k).strip()[:64]
                if not ks:
                    continue
                if isinstance(v, str):
                    meta_out[ks] = v.strip()[:MAX_META_STR_LEN]
                elif v is not None:
                    meta_out[ks] = str(v).strip()[:MAX_META_STR_LEN]
            if meta_out:
                row["meta"] = meta_out
        out.append(row)
    return (out, None)

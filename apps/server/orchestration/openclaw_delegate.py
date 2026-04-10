"""HTTP delegate + webhook verification for OpenClaw-compatible multi-agent runtimes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from django.core.cache import cache

from orchestration.metadata_context import extract_delegate_context_bundle
from orchestration.openclaw_callback_artifacts import OPENCLAW_CALLBACK_SCHEMA

logger = logging.getLogger(__name__)


def parse_agent_config(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("openclaw_agent_config_json_invalid")
        return {}


def resolve_agent_ids(
    *,
    metadata: dict[str, Any],
    risk_tier: str,
    config_json: str,
) -> list[str]:
    """Resolve agent id list: metadata.openclaw.agents > by_risk > default_agents."""
    cfg = parse_agent_config(config_json)
    oc = metadata.get("openclaw") if isinstance(metadata.get("openclaw"), dict) else {}
    direct = oc.get("agents")
    if isinstance(direct, list) and all(isinstance(x, str) for x in direct):
        return list(direct)
    by_risk = cfg.get("by_risk") if isinstance(cfg.get("by_risk"), dict) else {}
    if isinstance(by_risk.get(risk_tier), list):
        return [str(x) for x in by_risk[risk_tier]]
    defaults = cfg.get("default_agents")
    if isinstance(defaults, list):
        return [str(x) for x in defaults]
    return []


def build_callback_url(public_base: str) -> str | None:
    if not public_base:
        return None
    return f"{public_base}/api/v1/integrations/openclaw/callback/"


def build_delegate_status_snapshot(settings_obj: Any) -> dict[str, Any]:
    """Sanitized operator-facing delegate settings (no webhook secret)."""
    pub = (getattr(settings_obj, "CLAWAGORA_PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    delegate_url = (getattr(settings_obj, "CLAWAGORA_OPENCLAW_DELEGATE_URL", "") or "").strip()
    raw_agents = getattr(settings_obj, "CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON", "") or ""
    cfg = parse_agent_config(raw_agents)
    default_agents = cfg.get("default_agents") if isinstance(cfg.get("default_agents"), list) else []
    by_risk = cfg.get("by_risk") if isinstance(cfg.get("by_risk"), dict) else {}
    by_risk_keys = sorted(str(k) for k in by_risk.keys())
    return {
        "enabled": bool(getattr(settings_obj, "CLAWAGORA_OPENCLAW_DELEGATE_ENABLED", False)),
        "url_configured": bool(delegate_url),
        "delegate_url": delegate_url,
        "public_base_url": pub,
        "callback_url": build_callback_url(pub),
        "webhook_secret_configured": bool(
            (getattr(settings_obj, "CLAWAGORA_OPENCLAW_WEBHOOK_SECRET", "") or "").strip()
        ),
        "delegate_timeout_sec": float(getattr(settings_obj, "CLAWAGORA_OPENCLAW_DELEGATE_TIMEOUT_SEC", 60.0)),
        "callback_guard_cache_backend": (
            "redis"
            if bool((getattr(settings_obj, "CLAWAGORA_CACHE_URL", "") or "").strip())
            else "locmem"
        ),
        "knowledge": {
            "capability_require_sha256": bool(
                getattr(settings_obj, "CLAWAGORA_CAPABILITY_REQUIRE_SHA256", False)
            ),
            "capability_require_source_url": bool(
                getattr(settings_obj, "CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL", False)
            ),
        },
        "agent_config": {
            "default_agents": [str(x) for x in default_agents[:32]],
            "by_risk_tiers": by_risk_keys,
        },
    }


def sign_body(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_callback_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not secret or not signature_header:
        return False
    sig = signature_header.strip()
    if sig.lower().startswith("sha256="):
        sig = sig.split("=", 1)[1].strip()
    expected = sign_body(secret, body)
    try:
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


def verify_callback_guard(
    *,
    timestamp_header: str | None,
    nonce_header: str | None,
    max_skew_sec: int,
    nonce_ttl_sec: int,
) -> tuple[bool, str]:
    """Best-effort anti-replay guard using timestamp + nonce + cache add."""
    if not timestamp_header or not nonce_header:
        return (False, "missing_timestamp_or_nonce")
    ts_raw = str(timestamp_header).strip()
    nonce = str(nonce_header).strip()
    if not nonce or len(nonce) > 256:
        return (False, "invalid_nonce")
    try:
        ts = int(ts_raw)
    except (TypeError, ValueError):
        return (False, "invalid_timestamp")
    now = int(time.time())
    if abs(now - ts) > int(max_skew_sec):
        return (False, "timestamp_out_of_window")
    # Nonce must be globally single-use within TTL regardless of body content.
    # If we keyed by (nonce, body), an attacker could replay the same nonce with
    # modified payload and bypass the guard check.
    key = f"openclaw:callback:nonce:{nonce}"
    first_seen = cache.add(key, "1", timeout=int(nonce_ttl_sec))
    if not first_seen:
        return (False, "replay_detected")
    return (True, "ok")


def post_delegate(
    *,
    url: str,
    payload: dict[str, Any],
    api_key: str = "",
    timeout_sec: float = 60.0,
) -> tuple[bool, int | None, str]:
    """POST JSON to delegate URL. Returns (ok, http_status, detail)."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return (200 <= status < 300, status, "ok")
    except urllib.error.HTTPError as exc:
        return (False, exc.code, exc.read()[:500].decode("utf-8", errors="replace"))
    except Exception as exc:
        return (False, None, str(exc)[:500])


def build_delegate_payload(
    *,
    task_id: str,
    input_text: str,
    metadata: dict[str, Any],
    risk_tier: str,
    agents: list[str],
    callback_url: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "clawagora.openclaw.delegate.v1",
        "task_id": task_id,
        "input_text": input_text,
        "metadata": metadata,
        "risk_tier": risk_tier,
        "agents": agents,
        "callback_url": callback_url,
        # Bridge may complete with optional top-level ``artifacts`` (see OPENCLAW_CALLBACK_SCHEMA).
        "callback_schema": OPENCLAW_CALLBACK_SCHEMA,
    }
    ctx = extract_delegate_context_bundle(metadata)
    if ctx:
        payload["context"] = ctx
    return payload

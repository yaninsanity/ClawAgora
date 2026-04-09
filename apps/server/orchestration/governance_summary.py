"""Aggregate read-only governance snapshot for operations dashboards."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache

from clawagora.prompts import PROMPT_REGISTRY
from clawagora.version import __version__ as clawagora_version
from orchestration.app_settings import prompt_circuit_config
from orchestration.models import CapabilityBundle, PolicyDraft
from orchestration.openclaw_delegate import build_delegate_status_snapshot
from orchestration.prompt_circuit import _circuit_cache_key, _metrics_cache_key


def _policy_block() -> dict[str, Any]:
    active = PolicyDraft.objects.filter(is_active=True).first()
    return {
        "has_active_policy": active is not None,
        "active_policy_id": str(active.id) if active else None,
        "active_policy_name": active.name if active else None,
        "active_policy_updated_at": active.updated_at.isoformat() if active else None,
        "draft_count": PolicyDraft.objects.count(),
    }


def _capability_block() -> dict[str, Any]:
    require_sha = bool(getattr(settings, "CLAWAGORA_CAPABILITY_REQUIRE_SHA256", False))
    require_url = bool(getattr(settings, "CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL", False))
    offenders: list[dict[str, Any]] = []
    for b in CapabilityBundle.objects.filter(is_active=True).order_by("slug"):
        reasons: list[str] = []
        if require_url and not (b.source_url or "").strip():
            reasons.append("missing_source_url")
        if require_sha and len((b.source_sha256 or "").strip()) != 64:
            reasons.append("missing_or_invalid_sha256")
        if reasons:
            offenders.append({"id": str(b.id), "slug": b.slug, "reasons": reasons})
    return {
        "require_sha256": require_sha,
        "require_source_url": require_url,
        "active_bundle_count": CapabilityBundle.objects.filter(is_active=True).count(),
        "total_bundle_count": CapabilityBundle.objects.count(),
        "offender_count": len(offenders),
        "offenders": offenders[:100],
    }


def _prompt_block() -> dict[str, Any]:
    cfg = prompt_circuit_config()
    keys_out: list[dict[str, Any]] = []
    for prompt_key in sorted(PROMPT_REGISTRY.keys()):
        forced = cache.get(_circuit_cache_key(prompt_key))
        versions: list[dict[str, Any]] = []
        for v in PROMPT_REGISTRY[prompt_key]:
            mk = _metrics_cache_key(prompt_key, v.version)
            raw = cache.get(mk)
            metrics = raw if isinstance(raw, dict) else None
            versions.append(
                {
                    "version": v.version,
                    "rollout": v.rollout,
                    "metrics": metrics,
                }
            )
        keys_out.append(
            {
                "prompt_key": prompt_key,
                "circuit_forced_version": forced,
                "versions": versions,
            }
        )
    return {
        "circuit_breaker": {
            "enabled": cfg.enabled,
            "min_samples": cfg.min_samples,
            "error_rate_max": cfg.error_rate_max,
            "avg_cost_usd_max": cfg.avg_cost_usd_max,
            "metrics_ttl_seconds": cfg.metrics_ttl_seconds,
            "cooldown_seconds": cfg.cooldown_seconds,
            "fallback_version_default": cfg.fallback_version,
        },
        "registry_keys": keys_out,
    }


def build_governance_summary() -> dict[str, Any]:
    """Return a JSON-serializable governance summary (policy + knowledge + prompts + integration hints)."""
    delegate = build_delegate_status_snapshot(settings)
    return {
        "schema": "clawagora.governance.summary.v1",
        "version": clawagora_version,
        "policy": _policy_block(),
        "capabilities": _capability_block(),
        "prompts": _prompt_block(),
        "integrations": {
            "openclaw_delegate": {
                "enabled": delegate.get("enabled"),
                "url_configured": delegate.get("url_configured"),
                "callback_url": delegate.get("callback_url"),
                "callback_guard_cache_backend": delegate.get("callback_guard_cache_backend"),
                "knowledge": delegate.get("knowledge"),
            },
        },
    }

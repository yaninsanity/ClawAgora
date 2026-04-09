"""Prompt version circuit breaker: cache-backed metrics and forced rollback."""

from __future__ import annotations

import logging
from typing import Any

from django.core.cache import cache

from clawagora.kernel.pipeline import PipelineResult
from clawagora.prompts import PROMPT_REGISTRY
from orchestration.app_settings import prompt_circuit_config

logger = logging.getLogger(__name__)

_METRICS_PREFIX = "prompt_circuit_metrics:"
_CIRCUIT_PREFIX = "prompt_circuit_open:"


def _metrics_cache_key(prompt_key: str, version: str) -> str:
    return f"{_METRICS_PREFIX}{prompt_key}:{version}"


def _circuit_cache_key(prompt_key: str) -> str:
    return f"{_CIRCUIT_PREFIX}{prompt_key}"


def _fallback_version_for_key(prompt_key: str, preferred: str) -> str:
    variants = PROMPT_REGISTRY.get(prompt_key)
    if not variants:
        return preferred
    for v in variants:
        if v.version == preferred:
            return preferred
    return variants[0].version


def merge_circuit_overrides_into_metadata(metadata: dict[str, Any]) -> None:
    """Merge active circuit-open overrides into metadata['prompt_forced_versions'].

    Circuit overrides win over any operator-provided forced versions so rollback
    cannot be accidentally bypassed.
    """
    cfg = prompt_circuit_config()
    if not cfg.enabled:
        return
    base = dict(metadata.get("prompt_forced_versions") or {})
    circuit: dict[str, str] = {}
    for prompt_key in PROMPT_REGISTRY:
        forced = cache.get(_circuit_cache_key(prompt_key))
        if forced:
            circuit[prompt_key] = str(forced)
    if not circuit:
        metadata["prompt_forced_versions"] = base
        return
    metadata["prompt_forced_versions"] = {**base, **circuit}


def _cost_for_key_version(
    llm_usage: list[dict[str, Any]] | None, *, prompt_key: str, version: str
) -> float:
    if not llm_usage:
        return 0.0
    total = 0.0
    for row in llm_usage:
        if not isinstance(row, dict):
            continue
        if row.get("prompt_key") == prompt_key and row.get("prompt_version") == version:
            try:
                total += float(row.get("est_cost_usd", 0.0))
            except (TypeError, ValueError):
                pass
    return total


def _outcome_for_trace_entry(
    *,
    stage_name: str,
    success: bool,
    error_stage: str | None,
) -> bool | None:
    """Return True (success), False (failure), or None (do not record this key)."""
    if success:
        return True
    err = (error_stage or "").strip().lower()
    if err == "classify":
        if stage_name == "classify":
            return False
        return None
    if err == "synthesize":
        if stage_name == "classify":
            return True
        if stage_name == "synthesize":
            return False
        return None
    # validate, plan, dispatch, execute — classify (and synthesize if present) did not fail as LLM fault
    if stage_name == "classify":
        return True
    if stage_name == "synthesize":
        # Reached synthesize stage but failed earlier non-LLM — should not happen if trace is consistent
        return True
    return None


def _iter_trace_metrics(
    trace: dict[str, Any] | None,
    *,
    success: bool,
    error_stage: str | None,
    llm_usage: list[dict[str, Any]] | None,
) -> list[tuple[str, str, bool, float]]:
    if not trace:
        return []
    out: list[tuple[str, str, bool, float]] = []
    for stage_name, info in trace.items():
        if not isinstance(info, dict):
            continue
        pk = info.get("prompt_key")
        pv = info.get("prompt_version")
        if not isinstance(pk, str) or not isinstance(pv, str):
            continue
        oc = _outcome_for_trace_entry(
            stage_name=stage_name,
            success=success,
            error_stage=error_stage,
        )
        if oc is None:
            continue
        cost = _cost_for_key_version(llm_usage, prompt_key=pk, version=pv)
        out.append((pk, pv, oc, cost))
    return out


def _read_metrics_blob(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "n": int(raw.get("n", 0)),
            "fail": int(raw.get("fail", 0)),
            "cost_sum": float(raw.get("cost_sum", 0.0)),
        }
    return {"n": 0, "fail": 0, "cost_sum": 0.0}


def _should_trip(
    *,
    n: int,
    fail: int,
    cost_sum: float,
    cfg,
) -> bool:
    if n < cfg.min_samples:
        return False
    fail_rate = fail / n if n else 0.0
    if fail_rate >= cfg.error_rate_max:
        return True
    if cfg.avg_cost_usd_max > 0.0:
        avg_cost = cost_sum / n if n else 0.0
        if avg_cost >= cfg.avg_cost_usd_max:
            return True
    return False


def record_prompt_circuit_outcome(
    result: PipelineResult,
    *,
    success: bool,
) -> None:
    """Update per-(prompt_key, version) metrics and open circuits when thresholds are exceeded."""
    cfg = prompt_circuit_config()
    if not cfg.enabled:
        return
    trace = (result.envelope.metadata or {}).get("prompt_trace")
    if not isinstance(trace, dict):
        return
    llm_usage = (result.envelope.metadata or {}).get("llm_usage")
    if llm_usage is not None and not isinstance(llm_usage, list):
        llm_usage = None
    rows = _iter_trace_metrics(
        trace,
        success=success,
        error_stage=result.error_stage,
        llm_usage=llm_usage,
    )
    if not rows:
        return
    ttl = cfg.metrics_ttl_seconds
    fb_default = cfg.fallback_version
    for prompt_key, version, ok, cost in rows:
        key = _metrics_cache_key(prompt_key, version)
        blob = _read_metrics_blob(cache.get(key))
        blob["n"] += 1
        if not ok:
            blob["fail"] += 1
        blob["cost_sum"] = float(blob["cost_sum"]) + float(cost)
        cache.set(key, blob, timeout=ttl)

        if _should_trip(
            n=blob["n"],
            fail=blob["fail"],
            cost_sum=blob["cost_sum"],
            cfg=cfg,
        ):
            fb = _fallback_version_for_key(prompt_key, fb_default)
            ck = _circuit_cache_key(prompt_key)
            prev = cache.get(ck)
            cache.set(ck, fb, timeout=cfg.cooldown_seconds)
            if prev != fb:
                logger.warning(
                    "prompt_circuit_opened prompt_key=%s from_version=%s forced_version=%s "
                    "n=%s fail=%s cost_sum=%.8f",
                    prompt_key,
                    version,
                    fb,
                    blob["n"],
                    blob["fail"],
                    blob["cost_sum"],
                )

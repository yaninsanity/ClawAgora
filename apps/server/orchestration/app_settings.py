"""Explicit ClawAgora tunables from django.conf.settings.

Avoids getattr(..., default) on settings: defaults live only in settings.py so
tests use override_settings and production has one source of truth.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

ExecutionMode = Literal["sync", "async"]


@dataclass(frozen=True, slots=True)
class HealConfig:
    enabled: bool
    stale_running_seconds: int
    stale_queued_seconds: int
    requeue_stale_queued: bool
    stale_pending_approval_seconds: int
    expire_pending_approval: bool


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """LLM backend configuration read from CLAWAGORA_MODEL_* settings."""

    provider: str  # "null" | "ollama" | "openai_compat"
    url: str  # base URL of the model server
    name: str  # model identifier / tag
    api_key: str  # bearer token (empty = unauthenticated)
    timeout: int  # per-request timeout in seconds
    temperature: float
    max_tokens: int
    input_cost_per_mtok_usd: float
    output_cost_per_mtok_usd: float
    token_chars_estimate: int


@dataclass(frozen=True, slots=True)
class ApprovalGateConfig:
    """Which HumanApprovalGate to activate and its parameters.

    mode:
        "auto"          — always approve (default, no human review).
        "pending_human" — PENDING for tasks at or above *review_at* tier.
        "risk_based"    — REJECTED (hard block) at or above *reject_at* tier.
    quorum:
        Number of approvers; majority threshold = quorum//2+1.
        quorum=1 keeps the legacy single-operator behaviour.
    review_at / reject_at:
        Risk tier strings: "low" | "medium" | "high".
    """

    mode: str  # "auto" | "pending_human" | "risk_based"
    quorum: int  # applies to pending_human only
    review_at: str  # pending_human: tier that triggers review
    reject_at: str  # risk_based: tier that triggers auto-rejection


@dataclass(frozen=True, slots=True)
class GovernanceLeaderboardConfig:
    delta_gain: float
    success_gain: float
    incident_penalty: float
    efficiency_success_gain: float
    efficiency_incident_gain: float
    recommended_weight_min: float
    recommended_weight_max: float


@dataclass(frozen=True, slots=True)
class PromptCircuitConfig:
    """Prompt version auto-rollback based on observed error rate and estimated LLM cost."""

    enabled: bool
    min_samples: int
    error_rate_max: float
    avg_cost_usd_max: float
    metrics_ttl_seconds: int
    cooldown_seconds: int
    fallback_version: str


@dataclass(frozen=True, slots=True)
class GovernanceRuntimeConfig:
    leaderboard_scan_limit: int
    alert_scan_limit: int
    response_cache_ttl_seconds: int
    list_default_limit: int
    list_max_limit: int
    dead_letter_default_limit: int
    dead_letter_max_limit: int
    replay_preview_max_items: int
    task_list_default_limit: int
    task_list_max_limit: int


@dataclass(frozen=True, slots=True)
class RiskKeywordConfig:
    high_patterns: tuple[str, ...]
    medium_patterns: tuple[str, ...]


def approval_gate_config() -> ApprovalGateConfig:
    return ApprovalGateConfig(
        mode=settings.CLAWAGORA_APPROVAL_GATE,
        quorum=settings.CLAWAGORA_APPROVAL_QUORUM,
        review_at=settings.CLAWAGORA_APPROVAL_REVIEW_AT,
        reject_at=settings.CLAWAGORA_APPROVAL_REJECT_AT,
    )


def allowed_voters() -> frozenset[str]:
    """Return the set of voter_ids authorised to cast approval votes.

    An empty frozenset means the allowlist is disabled — all voters are accepted.
    """
    return frozenset(settings.CLAWAGORA_APPROVAL_ALLOWED_VOTERS)


def policy_write_key() -> str:
    """Return the bearer token required for policy write operations.

    Falls back to the standard API key when CLAWAGORA_POLICY_KEY is not set,
    so single-key deployments are unaffected.
    """
    key = settings.CLAWAGORA_POLICY_KEY
    return key if key else settings.CLAWAGORA_API_KEY


def governance_write_key() -> str:
    key = settings.CLAWAGORA_GOVERNANCE_KEY
    if key:
        return key
    return policy_write_key()


def governance_daily_budget(level: str) -> float:
    if level == "minimal":
        return settings.CLAWAGORA_GOVERNANCE_DAILY_BUDGET_MINIMAL_BPS / 10000.0
    if level == "strict":
        return settings.CLAWAGORA_GOVERNANCE_DAILY_BUDGET_STRICT_BPS / 10000.0
    return settings.CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS / 10000.0


def governance_alert_max_retries() -> int:
    return settings.CLAWAGORA_GOVERNANCE_ALERT_MAX_RETRIES


def governance_snapshot_ttl_seconds() -> int:
    return settings.CLAWAGORA_GOVERNANCE_SNAPSHOT_TTL_SECONDS


def governance_signing_key() -> str:
    key = settings.CLAWAGORA_GOVERNANCE_SIGNING_KEY
    if key:
        return key
    return governance_write_key()


def governance_alert_budget_threshold() -> float:
    return settings.CLAWAGORA_GOVERNANCE_ALERT_BUDGET_NEAR_EXHAUSTED_BPS / 10000.0


def governance_alert_low_efficiency_threshold() -> float:
    return settings.CLAWAGORA_GOVERNANCE_ALERT_LOW_EFFICIENCY_BPS / 10000.0


def governance_leaderboard_config() -> GovernanceLeaderboardConfig:
    return GovernanceLeaderboardConfig(
        delta_gain=settings.CLAWAGORA_GOVERNANCE_LB_DELTA_GAIN_BPS / 10000.0,
        success_gain=settings.CLAWAGORA_GOVERNANCE_LB_SUCCESS_GAIN_BPS / 10000.0,
        incident_penalty=settings.CLAWAGORA_GOVERNANCE_LB_INCIDENT_PENALTY_BPS / 10000.0,
        efficiency_success_gain=settings.CLAWAGORA_GOVERNANCE_LB_EFF_SUCCESS_BPS / 10000.0,
        efficiency_incident_gain=settings.CLAWAGORA_GOVERNANCE_LB_EFF_INCIDENT_BPS / 10000.0,
        recommended_weight_min=settings.CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MIN_BPS / 10000.0,
        recommended_weight_max=settings.CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MAX_BPS / 10000.0,
    )


def governance_runtime_config() -> GovernanceRuntimeConfig:
    return GovernanceRuntimeConfig(
        leaderboard_scan_limit=settings.CLAWAGORA_GOVERNANCE_LEADERBOARD_SCAN_LIMIT,
        alert_scan_limit=settings.CLAWAGORA_GOVERNANCE_ALERT_SCAN_LIMIT,
        response_cache_ttl_seconds=settings.CLAWAGORA_GOVERNANCE_RESPONSE_CACHE_TTL_SECONDS,
        list_default_limit=settings.CLAWAGORA_GOVERNANCE_LIST_DEFAULT_LIMIT,
        list_max_limit=settings.CLAWAGORA_GOVERNANCE_LIST_MAX_LIMIT,
        dead_letter_default_limit=settings.CLAWAGORA_GOVERNANCE_DEAD_LETTER_DEFAULT_LIMIT,
        dead_letter_max_limit=settings.CLAWAGORA_GOVERNANCE_DEAD_LETTER_MAX_LIMIT,
        replay_preview_max_items=settings.CLAWAGORA_GOVERNANCE_REPLAY_PREVIEW_MAX_ITEMS,
        task_list_default_limit=settings.CLAWAGORA_TASK_LIST_DEFAULT_LIMIT,
        task_list_max_limit=settings.CLAWAGORA_TASK_LIST_MAX_LIMIT,
    )


def risk_keyword_config() -> RiskKeywordConfig:
    return RiskKeywordConfig(
        high_patterns=tuple(settings.CLAWAGORA_RISK_HIGH_PATTERNS),
        medium_patterns=tuple(settings.CLAWAGORA_RISK_MEDIUM_PATTERNS),
    )


def heal_config() -> HealConfig:
    return HealConfig(
        enabled=settings.CLAWAGORA_HEAL_ENABLED,
        stale_running_seconds=settings.CLAWAGORA_STALE_RUNNING_SECONDS,
        stale_queued_seconds=settings.CLAWAGORA_STALE_QUEUED_SECONDS,
        requeue_stale_queued=settings.CLAWAGORA_HEAL_REQUEUE_STALE_QUEUED,
        stale_pending_approval_seconds=settings.CLAWAGORA_STALE_PENDING_APPROVAL_SECONDS,
        expire_pending_approval=settings.CLAWAGORA_HEAL_EXPIRE_PENDING_APPROVAL,
    )


def prompt_circuit_config() -> PromptCircuitConfig:
    return PromptCircuitConfig(
        enabled=settings.CLAWAGORA_PROMPT_CIRCUIT_ENABLED,
        min_samples=settings.CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES,
        error_rate_max=settings.CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX,
        avg_cost_usd_max=settings.CLAWAGORA_PROMPT_CIRCUIT_AVG_COST_USD_MAX,
        metrics_ttl_seconds=settings.CLAWAGORA_PROMPT_CIRCUIT_METRICS_TTL_SECONDS,
        cooldown_seconds=settings.CLAWAGORA_PROMPT_CIRCUIT_COOLDOWN_SECONDS,
        fallback_version=settings.CLAWAGORA_PROMPT_CIRCUIT_FALLBACK_VERSION,
    )


def model_config() -> ModelConfig:
    return ModelConfig(
        provider=settings.CLAWAGORA_MODEL_PROVIDER,
        url=settings.CLAWAGORA_MODEL_URL,
        name=settings.CLAWAGORA_MODEL_NAME,
        api_key=settings.CLAWAGORA_MODEL_API_KEY,
        timeout=settings.CLAWAGORA_MODEL_TIMEOUT,
        temperature=settings.CLAWAGORA_MODEL_TEMPERATURE,
        max_tokens=settings.CLAWAGORA_MODEL_MAX_TOKENS,
        input_cost_per_mtok_usd=settings.CLAWAGORA_MODEL_COST_INPUT_PER_MTOK_USD,
        output_cost_per_mtok_usd=settings.CLAWAGORA_MODEL_COST_OUTPUT_PER_MTOK_USD,
        token_chars_estimate=settings.CLAWAGORA_MODEL_TOKEN_CHARS_ESTIMATE,
    )


def is_rq_stack_active() -> bool:
    """Package importable and registered in INSTALLED_APPS (queue + worker path)."""
    if importlib.util.find_spec("django_rq") is None:
        return False
    return "django_rq" in settings.INSTALLED_APPS


def default_execution_mode() -> ExecutionMode:
    mode = settings.CLAWAGORA_EXECUTION_MODE
    if mode not in ("sync", "async"):
        raise ImproperlyConfigured(
            f"CLAWAGORA_EXECUTION_MODE is invalid; check settings loading (got {mode!r})"
        )
    return mode

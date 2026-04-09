from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from clawagora_server.env_parsing import (
    parse_execution_mode,
    parse_log_format,
    parse_log_level,
    parse_non_negative_float,
    parse_positive_int,
)
from clawagora_server.logging_config import build_logging_dict


def _optional_app(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _parse_csv_patterns(raw: str | None, *, default: tuple[str, ...]) -> list[str]:
    if raw is None or raw.strip() == "":
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

if not DEBUG:
    if not SECRET_KEY or SECRET_KEY == "dev-insecure-change-me":
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0")

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()
]

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "0") == "1"

CLAWAGORA_MAX_INPUT_CHARS = parse_positive_int(
    "CLAWAGORA_MAX_INPUT_CHARS",
    os.environ.get("CLAWAGORA_MAX_INPUT_CHARS"),
    256000,
    minimum=1,
)
CLAWAGORA_MAX_METADATA_KEYS = parse_positive_int(
    "CLAWAGORA_MAX_METADATA_KEYS",
    os.environ.get("CLAWAGORA_MAX_METADATA_KEYS"),
    64,
    minimum=1,
)
CLAWAGORA_MAX_METADATA_BYTES = parse_positive_int(
    "CLAWAGORA_MAX_METADATA_BYTES",
    os.environ.get("CLAWAGORA_MAX_METADATA_BYTES"),
    65536,
    minimum=1,
)

# Capability / knowledge bundles (GET|POST /api/v1/capabilities/).
# CLAWAGORA_CAPABILITY_REQUIRE_SHA256=1      active bundles must pin source_sha256 (64 hex)
# CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL=1  active bundles must set source_url
# ---------------------------------------------------------------------------
CLAWAGORA_CAPABILITY_REQUIRE_SHA256: bool = (
    os.environ.get("CLAWAGORA_CAPABILITY_REQUIRE_SHA256", "0").strip() == "1"
)
CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL: bool = (
    os.environ.get("CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL", "0").strip() == "1"
)

CLAWAGORA_EXECUTION_MODE = parse_execution_mode(os.environ.get("CLAWAGORA_EXECUTION_MODE"))

CLAWAGORA_API_KEY: str = os.environ.get("CLAWAGORA_API_KEY", "").strip()
CLAWAGORA_EXPOSE_ERROR_DETAIL: bool = (
    os.environ.get("CLAWAGORA_EXPOSE_ERROR_DETAIL", "").strip() == "1"
)

# ---------------------------------------------------------------------------
# Model provider — pluggable LLM backend for classification and synthesis.
#
# CLAWAGORA_MODEL_PROVIDER   "null" (default, regex-only) | "ollama" | "openai_compat"
# CLAWAGORA_MODEL_URL        Base URL of the model server. Default: http://localhost:11434
# CLAWAGORA_MODEL_NAME       Model identifier. Default: gemma3:4b (can be gemma4 / qwen / llama / etc.)
# CLAWAGORA_MODEL_API_KEY    Bearer token for openai_compat endpoints (leave empty for local).
# CLAWAGORA_MODEL_TIMEOUT    Per-request timeout in seconds. Default: 30
#
# Quick start with Ollama + Gemma 3:
#   ollama pull gemma3:4b
#   CLAWAGORA_MODEL_PROVIDER=ollama CLAWAGORA_MODEL_NAME=gemma4:latest ./scripts/dev.sh
#   CLAWAGORA_MODEL_PROVIDER=openai_compat CLAWAGORA_MODEL_URL=http://localhost:11434 CLAWAGORA_MODEL_NAME=gemma4:latest ./scripts/dev.sh
# ---------------------------------------------------------------------------
CLAWAGORA_MODEL_PROVIDER: str = os.environ.get("CLAWAGORA_MODEL_PROVIDER", "null").strip()
CLAWAGORA_MODEL_URL: str = os.environ.get("CLAWAGORA_MODEL_URL", "http://localhost:11434").strip()
CLAWAGORA_MODEL_NAME: str = os.environ.get("CLAWAGORA_MODEL_NAME", "gemma3:4b").strip()
CLAWAGORA_MODEL_API_KEY: str = os.environ.get("CLAWAGORA_MODEL_API_KEY", "").strip()
CLAWAGORA_MODEL_TIMEOUT: int = parse_positive_int(
    "CLAWAGORA_MODEL_TIMEOUT",
    os.environ.get("CLAWAGORA_MODEL_TIMEOUT"),
    30,
    minimum=1,
)
CLAWAGORA_MODEL_TEMPERATURE: float = parse_non_negative_float(
    "CLAWAGORA_MODEL_TEMPERATURE",
    os.environ.get("CLAWAGORA_MODEL_TEMPERATURE"),
    0.0,
)
CLAWAGORA_MODEL_MAX_TOKENS: int = parse_positive_int(
    "CLAWAGORA_MODEL_MAX_TOKENS",
    os.environ.get("CLAWAGORA_MODEL_MAX_TOKENS"),
    512,
    minimum=1,
)
CLAWAGORA_MODEL_COST_INPUT_PER_MTOK_USD: float = parse_non_negative_float(
    "CLAWAGORA_MODEL_COST_INPUT_PER_MTOK_USD",
    os.environ.get("CLAWAGORA_MODEL_COST_INPUT_PER_MTOK_USD"),
    0.0,
)
CLAWAGORA_MODEL_COST_OUTPUT_PER_MTOK_USD: float = parse_non_negative_float(
    "CLAWAGORA_MODEL_COST_OUTPUT_PER_MTOK_USD",
    os.environ.get("CLAWAGORA_MODEL_COST_OUTPUT_PER_MTOK_USD"),
    0.0,
)
CLAWAGORA_MODEL_TOKEN_CHARS_ESTIMATE: int = parse_positive_int(
    "CLAWAGORA_MODEL_TOKEN_CHARS_ESTIMATE",
    os.environ.get("CLAWAGORA_MODEL_TOKEN_CHARS_ESTIMATE"),
    4,
    minimum=1,
)

# ---------------------------------------------------------------------------
# OpenClaw gateway (optional — external agent runtime integration).
#
# CLAWAGORA_OPENCLAW_ENABLED       "1" probes gateway from /api/v1/integrations/openclaw/status/
# CLAWAGORA_OPENCLAW_GATEWAY_URL   Base URL (no trailing slash required)
# CLAWAGORA_OPENCLAW_API_KEY       Optional bearer for gateway auth
# CLAWAGORA_OPENCLAW_STATUS_TIMEOUT_SEC  HTTP timeout for health probe
# ---------------------------------------------------------------------------
CLAWAGORA_OPENCLAW_ENABLED: bool = os.environ.get("CLAWAGORA_OPENCLAW_ENABLED", "0").strip() == "1"
CLAWAGORA_OPENCLAW_GATEWAY_URL: str = os.environ.get(
    "CLAWAGORA_OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789"
).strip()
CLAWAGORA_OPENCLAW_API_KEY: str = os.environ.get("CLAWAGORA_OPENCLAW_API_KEY", "").strip()
CLAWAGORA_OPENCLAW_STATUS_TIMEOUT_SEC: float = parse_non_negative_float(
    "CLAWAGORA_OPENCLAW_STATUS_TIMEOUT_SEC",
    os.environ.get("CLAWAGORA_OPENCLAW_STATUS_TIMEOUT_SEC"),
    3.0,
)

# Delegate tasks to an external OpenClaw-compatible HTTP bridge (multi-agent runtime).
# CLAWAGORA_OPENCLAW_DELEGATE_ENABLED     "1" allows metadata.openclaw.delegate=true to skip local pipeline
# CLAWAGORA_OPENCLAW_DELEGATE_URL         POST URL (JSON body); must accept ClawAgora payload schema
# CLAWAGORA_OPENCLAW_DELEGATE_TIMEOUT_SEC Per-request timeout
# CLAWAGORA_PUBLIC_BASE_URL               Public origin for callback URL embedded in delegate payload (no trailing slash)
# CLAWAGORA_OPENCLAW_WEBHOOK_SECRET       HMAC-SHA256 secret for X-ClawAgora-Signature on callbacks
# CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON    Optional JSON: {"default_agents":[],"by_risk":{"high":["a"]}}
# CLAWAGORA_OPENCLAW_CALLBACK_REQUIRE_GUARD "1" requires timestamp+nonce anti-replay headers
# CLAWAGORA_OPENCLAW_CALLBACK_MAX_SKEW_SEC  Allowed clock skew in seconds for callback timestamp
# CLAWAGORA_OPENCLAW_CALLBACK_NONCE_TTL_SEC Nonce replay lock TTL in seconds
# ---------------------------------------------------------------------------
CLAWAGORA_OPENCLAW_DELEGATE_ENABLED: bool = (
    os.environ.get("CLAWAGORA_OPENCLAW_DELEGATE_ENABLED", "0").strip() == "1"
)
CLAWAGORA_OPENCLAW_DELEGATE_URL: str = os.environ.get("CLAWAGORA_OPENCLAW_DELEGATE_URL", "").strip()
CLAWAGORA_OPENCLAW_DELEGATE_TIMEOUT_SEC: float = parse_non_negative_float(
    "CLAWAGORA_OPENCLAW_DELEGATE_TIMEOUT_SEC",
    os.environ.get("CLAWAGORA_OPENCLAW_DELEGATE_TIMEOUT_SEC"),
    60.0,
)
CLAWAGORA_PUBLIC_BASE_URL: str = os.environ.get("CLAWAGORA_PUBLIC_BASE_URL", "").strip().rstrip("/")
CLAWAGORA_OPENCLAW_WEBHOOK_SECRET: str = os.environ.get("CLAWAGORA_OPENCLAW_WEBHOOK_SECRET", "").strip()
_raw_oc_agents = (os.environ.get("CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON") or "").strip()
CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON: str = _raw_oc_agents
CLAWAGORA_OPENCLAW_CALLBACK_REQUIRE_GUARD: bool = (
    os.environ.get("CLAWAGORA_OPENCLAW_CALLBACK_REQUIRE_GUARD", "1").strip() == "1"
)
CLAWAGORA_OPENCLAW_CALLBACK_MAX_SKEW_SEC: int = parse_positive_int(
    "CLAWAGORA_OPENCLAW_CALLBACK_MAX_SKEW_SEC",
    os.environ.get("CLAWAGORA_OPENCLAW_CALLBACK_MAX_SKEW_SEC"),
    300,
    minimum=1,
)
CLAWAGORA_OPENCLAW_CALLBACK_NONCE_TTL_SEC: int = parse_positive_int(
    "CLAWAGORA_OPENCLAW_CALLBACK_NONCE_TTL_SEC",
    os.environ.get("CLAWAGORA_OPENCLAW_CALLBACK_NONCE_TTL_SEC"),
    900,
    minimum=1,
)

# ---------------------------------------------------------------------------
# Prompt circuit breaker — rollback prompt versions when error/cost exceeds thresholds.
#
# CLAWAGORA_PROMPT_CIRCUIT_ENABLED          "1" (default) | "0"
# CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES      Minimum observations per (key, version) before tripping.
# CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX   Trip when fail_count / n >= this (0.0–1.0).
# CLAWAGORA_PROMPT_CIRCUIT_AVG_COST_USD_MAX Trip when avg est_cost per sample >= this; 0 disables.
# CLAWAGORA_PROMPT_CIRCUIT_METRICS_TTL_SECONDS  Sliding window TTL for per-version counters.
# CLAWAGORA_PROMPT_CIRCUIT_COOLDOWN_SECONDS     How long forced fallback applies after a trip.
# CLAWAGORA_PROMPT_CIRCUIT_FALLBACK_VERSION     Version string to force for that prompt key (e.g. v1).
# ---------------------------------------------------------------------------
CLAWAGORA_PROMPT_CIRCUIT_ENABLED: bool = (
    os.environ.get("CLAWAGORA_PROMPT_CIRCUIT_ENABLED", "1").strip() == "1"
)
CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES: int = parse_positive_int(
    "CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES",
    os.environ.get("CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES"),
    5,
    minimum=1,
)
CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX: float = parse_non_negative_float(
    "CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX",
    os.environ.get("CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX"),
    0.25,
)
if CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX > 1.0:
    raise ImproperlyConfigured(
        "CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX must be <= 1.0 "
        f"(got {CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX})"
    )
CLAWAGORA_PROMPT_CIRCUIT_AVG_COST_USD_MAX: float = parse_non_negative_float(
    "CLAWAGORA_PROMPT_CIRCUIT_AVG_COST_USD_MAX",
    os.environ.get("CLAWAGORA_PROMPT_CIRCUIT_AVG_COST_USD_MAX"),
    0.0,
)
CLAWAGORA_PROMPT_CIRCUIT_METRICS_TTL_SECONDS: int = parse_positive_int(
    "CLAWAGORA_PROMPT_CIRCUIT_METRICS_TTL_SECONDS",
    os.environ.get("CLAWAGORA_PROMPT_CIRCUIT_METRICS_TTL_SECONDS"),
    3600,
    minimum=60,
)
CLAWAGORA_PROMPT_CIRCUIT_COOLDOWN_SECONDS: int = parse_positive_int(
    "CLAWAGORA_PROMPT_CIRCUIT_COOLDOWN_SECONDS",
    os.environ.get("CLAWAGORA_PROMPT_CIRCUIT_COOLDOWN_SECONDS"),
    600,
    minimum=60,
)
CLAWAGORA_PROMPT_CIRCUIT_FALLBACK_VERSION: str = os.environ.get(
    "CLAWAGORA_PROMPT_CIRCUIT_FALLBACK_VERSION", "v1"
).strip() or "v1"

LOG_LEVEL = parse_log_level(os.environ.get("LOG_LEVEL"))
LOG_FORMAT = parse_log_format(os.environ.get("LOG_FORMAT"))

CLAWAGORA_HEAL_ENABLED = os.environ.get("CLAWAGORA_HEAL_ENABLED", "1") == "1"
CLAWAGORA_STALE_RUNNING_SECONDS = parse_positive_int(
    "CLAWAGORA_STALE_RUNNING_SECONDS",
    os.environ.get("CLAWAGORA_STALE_RUNNING_SECONDS"),
    3600,
    minimum=1,
)
CLAWAGORA_STALE_QUEUED_SECONDS = parse_positive_int(
    "CLAWAGORA_STALE_QUEUED_SECONDS",
    os.environ.get("CLAWAGORA_STALE_QUEUED_SECONDS"),
    1800,
    minimum=1,
)
CLAWAGORA_HEAL_REQUEUE_STALE_QUEUED = (
    os.environ.get("CLAWAGORA_HEAL_REQUEUE_STALE_QUEUED", "0") == "1"
)
# Auto-reject approval requests that have been pending longer than this.
# Set to 0 to disable expiry (wait forever). Default: 86400 seconds (24 h).
CLAWAGORA_STALE_PENDING_APPROVAL_SECONDS = parse_positive_int(
    "CLAWAGORA_STALE_PENDING_APPROVAL_SECONDS",
    os.environ.get("CLAWAGORA_STALE_PENDING_APPROVAL_SECONDS"),
    86400,
    minimum=1,
)
CLAWAGORA_HEAL_EXPIRE_PENDING_APPROVAL = (
    os.environ.get("CLAWAGORA_HEAL_EXPIRE_PENDING_APPROVAL", "1") == "1"
)

# ---------------------------------------------------------------------------
# Risk keyword tiers used by RiskClassifier.
#
# Both vars accept comma-separated regex fragments.
# Keep patterns narrow to avoid false positives.
# ---------------------------------------------------------------------------
CLAWAGORA_RISK_HIGH_PATTERNS: list[str] = _parse_csv_patterns(
    os.environ.get("CLAWAGORA_RISK_HIGH_PATTERNS"),
    default=(
        r"\bprod\b",
        r"\bproduction\b",
        r"\bpayment\b",
        r"\bpii\b",
        r"\bsecrets?\b",
        r"\bcredentials?\b",
        r"private[-_ ]key",
        r"api[-_]?key",
        r"access[-_ ]token",
        r"\boauth\b",
        r"\bpassphrase\b",
        r"\bdrop\s+table\b",
        r"\bdrop\s+database\b",
        r"\bdrop\s+schema\b",
        r"\btruncate\b",
        r"\bdelete\s+from\b",
        r"\bdelete\s+all\b",
        r"\balter\s+table\b",
        r"\bgrant\s+\w",
        r"\brevoke\s+\w",
        r"rm\s+-[rRf]+",
        r"curl[^|]*\|\s*(?:ba?sh|sh|zsh|fish)",
        r"wget[^|]*\|\s*(?:ba?sh|sh|zsh|fish)",
        r"\bwipe\b",
        r"\bnuke\b",
        r"\berase\b",
        r"\bcompromise\b",
        r"\bexploit\b",
        r"\bbreach\b",
        r"\bexfiltrat",
        r"\bbackdoor\b",
        r"privilege.escalat",
        r"root.access",
        r"\bsudo\b",
    ),
)
CLAWAGORA_RISK_MEDIUM_PATTERNS: list[str] = _parse_csv_patterns(
    os.environ.get("CLAWAGORA_RISK_MEDIUM_PATTERNS"),
    default=(
        r"\bdeploy",
        r"\brelease\b",
        r"\bcustomer\b",
        r"\bwrite\s+to\s+(?:prod|database|db|disk|s3|storage)\b",
        r"\boverwrite\b",
        r"\bdelete\b",
        r"\bremove\b",
        r"\bupdate\b",
        r"\binsert\s+into\b",
        r"\bmigrat",
        r"\brollback\b",
        r"\bschema\b",
        r"\bdatabase\b",
        r"\brestart\b",
        r"\bdisable\b",
        r"\bterminate\b",
        r"\bshutdown\b",
    ),
)

# ---------------------------------------------------------------------------
# Executor thread pool — parallel plan step execution.
# CLAWAGORA_EXECUTOR_POOL_SIZE  Max worker threads for the TaskPipeline executor pool.
#                               Default: 8.  Set lower for CPU-bound workloads;
#                               set higher for I/O-bound workloads.
# ---------------------------------------------------------------------------
CLAWAGORA_EXECUTOR_POOL_SIZE: int = parse_positive_int(
    "CLAWAGORA_EXECUTOR_POOL_SIZE",
    os.environ.get("CLAWAGORA_EXECUTOR_POOL_SIZE"),
    8,
    minimum=1,
)

# ---------------------------------------------------------------------------
# Governance — default profile.
# CLAWAGORA_DEFAULT_GOVERNANCE_PROFILE  Profile name used when no profile is
#                                       specified in the request.  Operators
#                                       deploying a different profile should
#                                       set this to match their active profile.
#                                       Default: "constitutional_western"
# ---------------------------------------------------------------------------
CLAWAGORA_DEFAULT_GOVERNANCE_PROFILE: str = (
    os.environ.get("CLAWAGORA_DEFAULT_GOVERNANCE_PROFILE", "constitutional_western").strip().lower()
    or "constitutional_western"
)

# ---------------------------------------------------------------------------
# Approval gate — controls which gate OrchestrationService uses by default.
#
# CLAWAGORA_APPROVAL_GATE      "auto" (default) | "pending_human" | "risk_based"
# CLAWAGORA_APPROVAL_QUORUM    Voters needed; majority threshold = N//2+1.
#                              1 = single-operator (legacy). Use 3/5/7 for panels.
# CLAWAGORA_APPROVAL_REVIEW_AT Risk tier threshold for pending_human gate.
# CLAWAGORA_APPROVAL_REJECT_AT Risk tier threshold for risk_based gate.
# ---------------------------------------------------------------------------
CLAWAGORA_APPROVAL_GATE: str = os.environ.get("CLAWAGORA_APPROVAL_GATE", "auto").strip()
CLAWAGORA_APPROVAL_QUORUM: int = parse_positive_int(
    "CLAWAGORA_APPROVAL_QUORUM",
    os.environ.get("CLAWAGORA_APPROVAL_QUORUM"),
    1,
    minimum=1,
)
CLAWAGORA_APPROVAL_REVIEW_AT: str = os.environ.get("CLAWAGORA_APPROVAL_REVIEW_AT", "high").strip()
CLAWAGORA_APPROVAL_REJECT_AT: str = os.environ.get("CLAWAGORA_APPROVAL_REJECT_AT", "high").strip()

# ---------------------------------------------------------------------------
# 三权分立 — Separation of executive, judicial, and legislative authority.
#
# CLAWAGORA_APPROVAL_ALLOWED_VOTERS
#   Comma-separated list of voter_ids authorised to cast approval votes.
#   When non-empty, votes from any voter_id not in this list are rejected 403.
#   When empty (default), all voter_ids are accepted (backward-compatible).
#   Example: "alice,bob,carol"
#
# CLAWAGORA_POLICY_KEY
#   Separate bearer token required for policy write operations (POST/PATCH/DELETE
#   /api/v1/policies/ and /activate/).  Passed as X-Policy-Key header.
#   When empty (default), falls back to the standard CLAWAGORA_API_KEY so
#   existing single-key setups are unaffected.
#   Set to a different secret from CLAWAGORA_API_KEY to enforce that policy
#   writers and task submitters are different principals.
# ---------------------------------------------------------------------------
CLAWAGORA_APPROVAL_ALLOWED_VOTERS: list[str] = [
    v.strip()
    for v in os.environ.get("CLAWAGORA_APPROVAL_ALLOWED_VOTERS", "").split(",")
    if v.strip()
]
CLAWAGORA_POLICY_KEY: str = os.environ.get("CLAWAGORA_POLICY_KEY", "").strip()
CLAWAGORA_GOVERNANCE_KEY: str = os.environ.get("CLAWAGORA_GOVERNANCE_KEY", "").strip()
CLAWAGORA_GOVERNANCE_DAILY_BUDGET_MINIMAL_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_DAILY_BUDGET_MINIMAL_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_DAILY_BUDGET_MINIMAL_BPS"),
    6000,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS"),
    3500,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_DAILY_BUDGET_STRICT_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_DAILY_BUDGET_STRICT_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_DAILY_BUDGET_STRICT_BPS"),
    1800,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_ALERT_MAX_RETRIES: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_ALERT_MAX_RETRIES",
    os.environ.get("CLAWAGORA_GOVERNANCE_ALERT_MAX_RETRIES"),
    3,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_SNAPSHOT_TTL_SECONDS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_SNAPSHOT_TTL_SECONDS",
    os.environ.get("CLAWAGORA_GOVERNANCE_SNAPSHOT_TTL_SECONDS"),
    20,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_SIGNING_KEY: str = os.environ.get(
    "CLAWAGORA_GOVERNANCE_SIGNING_KEY", ""
).strip()
CLAWAGORA_GOVERNANCE_ALERT_BUDGET_NEAR_EXHAUSTED_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_ALERT_BUDGET_NEAR_EXHAUSTED_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_ALERT_BUDGET_NEAR_EXHAUSTED_BPS"),
    9000,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_ALERT_LOW_EFFICIENCY_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_ALERT_LOW_EFFICIENCY_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_ALERT_LOW_EFFICIENCY_BPS"),
    4500,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_LB_DELTA_GAIN_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LB_DELTA_GAIN_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_LB_DELTA_GAIN_BPS"),
    9000,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_LB_SUCCESS_GAIN_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LB_SUCCESS_GAIN_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_LB_SUCCESS_GAIN_BPS"),
    2000,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_LB_INCIDENT_PENALTY_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LB_INCIDENT_PENALTY_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_LB_INCIDENT_PENALTY_BPS"),
    1200,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_LB_EFF_SUCCESS_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LB_EFF_SUCCESS_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_LB_EFF_SUCCESS_BPS"),
    7000,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_LB_EFF_INCIDENT_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LB_EFF_INCIDENT_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_LB_EFF_INCIDENT_BPS"),
    3000,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MIN_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MIN_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MIN_BPS"),
    4000,
    minimum=0,
)
CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MAX_BPS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MAX_BPS",
    os.environ.get("CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MAX_BPS"),
    22000,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_LEADERBOARD_SCAN_LIMIT: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LEADERBOARD_SCAN_LIMIT",
    os.environ.get("CLAWAGORA_GOVERNANCE_LEADERBOARD_SCAN_LIMIT"),
    500,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_ALERT_SCAN_LIMIT: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_ALERT_SCAN_LIMIT",
    os.environ.get("CLAWAGORA_GOVERNANCE_ALERT_SCAN_LIMIT"),
    200,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_RESPONSE_CACHE_TTL_SECONDS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_RESPONSE_CACHE_TTL_SECONDS",
    os.environ.get("CLAWAGORA_GOVERNANCE_RESPONSE_CACHE_TTL_SECONDS"),
    20,
    minimum=1,
)
CLAWAGORA_TASK_LIST_DEFAULT_LIMIT: int = parse_positive_int(
    "CLAWAGORA_TASK_LIST_DEFAULT_LIMIT",
    os.environ.get("CLAWAGORA_TASK_LIST_DEFAULT_LIMIT"),
    20,
    minimum=1,
)
CLAWAGORA_TASK_LIST_MAX_LIMIT: int = parse_positive_int(
    "CLAWAGORA_TASK_LIST_MAX_LIMIT",
    os.environ.get("CLAWAGORA_TASK_LIST_MAX_LIMIT"),
    200,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_LIST_DEFAULT_LIMIT: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LIST_DEFAULT_LIMIT",
    os.environ.get("CLAWAGORA_GOVERNANCE_LIST_DEFAULT_LIMIT"),
    20,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_LIST_MAX_LIMIT: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_LIST_MAX_LIMIT",
    os.environ.get("CLAWAGORA_GOVERNANCE_LIST_MAX_LIMIT"),
    100,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_DEAD_LETTER_DEFAULT_LIMIT: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_DEAD_LETTER_DEFAULT_LIMIT",
    os.environ.get("CLAWAGORA_GOVERNANCE_DEAD_LETTER_DEFAULT_LIMIT"),
    50,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_DEAD_LETTER_MAX_LIMIT: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_DEAD_LETTER_MAX_LIMIT",
    os.environ.get("CLAWAGORA_GOVERNANCE_DEAD_LETTER_MAX_LIMIT"),
    200,
    minimum=1,
)
CLAWAGORA_GOVERNANCE_REPLAY_PREVIEW_MAX_ITEMS: int = parse_positive_int(
    "CLAWAGORA_GOVERNANCE_REPLAY_PREVIEW_MAX_ITEMS",
    os.environ.get("CLAWAGORA_GOVERNANCE_REPLAY_PREVIEW_MAX_ITEMS"),
    100,
    minimum=1,
)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "orchestration",
]
if _optional_app("django_rq"):
    INSTALLED_APPS.append("django_rq")

RQ_QUEUES = {}
if _optional_app("django_rq"):
    RQ_QUEUES = {
        "clawagora": {
            "URL": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            "DEFAULT_TIMEOUT": int(os.environ.get("RQ_DEFAULT_TIMEOUT", "360")),
        },
    }

# Cache backend (used by callback replay guard and optional app caches).
# CLAWAGORA_CACHE_URL: when set to redis://..., enables shared cross-process nonce lock.
CLAWAGORA_CACHE_URL: str = os.environ.get("CLAWAGORA_CACHE_URL", "").strip()
if CLAWAGORA_CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CLAWAGORA_CACHE_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "clawagora-default",
        }
    }

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "orchestration.middleware.RequestIdMiddleware",
]

ROOT_URLCONF = "clawagora_server.urls"

TEMPLATES: list = []

WSGI_APPLICATION = "clawagora_server.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

_pg_host = os.environ.get("POSTGRES_HOST")
if _pg_host:
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "clawagora"),
        "USER": os.environ.get("POSTGRES_USER", "clawagora"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "clawagora"),
        "HOST": _pg_host,
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

_data_upload = int(os.environ.get("DATA_UPLOAD_MAX_BYTES", str(2 * 1024 * 1024)))
DATA_UPLOAD_MAX_MEMORY_SIZE = _data_upload
FILE_UPLOAD_MAX_MEMORY_SIZE = _data_upload

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["orchestration.permissions.OptionalApiKeyPermission"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "orchestration.api_exceptions.envelope_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("CLAWAGORA_THROTTLE_RATE", "120/minute"),
    },
}

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]

LOGGING = build_logging_dict(log_level=LOG_LEVEL, log_format=LOG_FORMAT)

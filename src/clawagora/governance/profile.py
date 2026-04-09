from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

from clawagora.config import GOVERNANCE_CONFIG, GOVERNANCE_LEVEL_POLICIES

CONSTITUTIONAL_WESTERN_ROLES: tuple[str, ...] = (
    "Intake Clerk",
    "Policy Drafter",
    "Compliance Counsel",
    "Judicial Review Board",
    "Executive Dispatch",
    "Inspector General",
)

# Registry: profile name → roles tuple.
# Built-in profiles are pre-seeded; downstream packages can call
# register_profile_roles() to add their own governance structures without
# forking this module.
_PROFILE_ROLES: dict[str, tuple[str, ...]] = {
    "constitutional_western": CONSTITUTIONAL_WESTERN_ROLES,
}
_DEFAULT_ROLES: tuple[str, ...] = ("General Coordinator",)


def register_profile_roles(profile: str, roles: tuple[str, ...] | list[str]) -> None:
    """Register a custom governance profile role sequence.

    Call this once at application startup (e.g. in AppConfig.ready) to
    add a named profile without modifying library source.

    Example::

        from clawagora.governance.profile import register_profile_roles
        register_profile_roles("my_corp", ("Risk Analyst", "Approver", "Auditor"))
    """
    if not roles:
        raise ValueError("roles must be non-empty")
    _PROFILE_ROLES[profile.strip().lower()] = tuple(roles)


@dataclass(frozen=True, slots=True)
class GovernanceContext:
    profile: str
    level: str
    roles: tuple[str, ...]
    role_weights: dict[str, float]

    def role_for_step(self, index: int) -> str:
        if not self.roles:
            return "General Coordinator"
        return self.roles[index % len(self.roles)]

    def weight_for_role(self, role: str) -> float:
        return self.role_weights.get(role, GOVERNANCE_CONFIG.default_role_weight)


def build_governance_context(metadata: dict[str, Any] | None) -> GovernanceContext:
    data = metadata or {}
    profile = str(data.get("governance_profile") or "neutral").strip().lower()
    level = resolve_governance_level(data)
    roles = _PROFILE_ROLES.get(profile, _DEFAULT_ROLES)
    return GovernanceContext(
        profile=profile,
        level=level,
        roles=roles,
        role_weights=_resolve_role_weights(roles, data, level=level),
    )


def resolve_governance_level(metadata: dict[str, Any] | None) -> str:
    raw = str((metadata or {}).get("governance_level") or "balanced").strip().lower()
    return raw if raw in GOVERNANCE_LEVEL_POLICIES else "balanced"


def governance_level_policy(level: str) -> dict[str, float]:
    policy = GOVERNANCE_LEVEL_POLICIES.get(level, GOVERNANCE_LEVEL_POLICIES["balanced"])
    return {
        "window": policy.window,
        "half_life_days": policy.half_life_days,
        "lifecycle_shift_cap": policy.lifecycle_shift_cap,
        "apply_alpha": policy.apply_alpha,
        "max_step_change": policy.max_step_change,
    }


def _resolve_role_weights(
    roles: tuple[str, ...], metadata: dict[str, Any], *, level: str
) -> dict[str, float]:
    policy = governance_level_policy(level)
    out: dict[str, float] = {r: GOVERNANCE_CONFIG.default_role_weight for r in roles}
    baseline = metadata.get("governance_baseline_weights")
    if isinstance(baseline, dict):
        for role in roles:
            if role in baseline:
                out[role] = _clamp(
                    _to_float(baseline.get(role), GOVERNANCE_CONFIG.default_role_weight),
                    GOVERNANCE_CONFIG.weight_min,
                    GOVERNANCE_CONFIG.weight_max,
                )
    feedback = metadata.get("accountability_feedback")
    if not isinstance(feedback, list):
        return out
    role_items: dict[str, list[dict[str, Any]]] = {r: [] for r in roles}
    for item in feedback:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in role_items:
            continue
        role_items[role].append(item)
    now = datetime.now(timezone.utc)
    for role in roles:
        total_feedback_shift = 0.0
        # Drift guard: use only the most recent lifecycle window per role.
        for item in role_items[role][-int(policy["window"]) :]:
            decay = _feedback_decay(
                now=now,
                observed_at=_parse_ts(item.get("observed_at")),
                half_life_days=policy["half_life_days"],
            )
            delta = _to_float(item.get("delta"), 0.0) * decay
            incidents = int(_to_float(item.get("incidents"), 0.0))
            total_feedback_shift += delta - (
                incidents * GOVERNANCE_CONFIG.incident_penalty_per_case * decay
            )
        # Drift guard: cap lifecycle contribution around baseline.
        cap = policy["lifecycle_shift_cap"]
        total_feedback_shift = _clamp(total_feedback_shift, -cap, cap)
        out[role] = _clamp(
            out[role] + total_feedback_shift,
            GOVERNANCE_CONFIG.weight_min,
            GOVERNANCE_CONFIG.weight_max,
        )
    return out


def _to_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    txt = raw.strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _feedback_decay(*, now: datetime, observed_at: datetime | None, half_life_days: float) -> float:
    if observed_at is None:
        return 1.0
    age_days = max((now - observed_at).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / max(half_life_days, 1.0))

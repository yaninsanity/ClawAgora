from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from clawagora.config import ACCOUNTABILITY_CONFIG
from clawagora.kernel.pipeline import PipelineResult
from clawagora.governance.profile import build_governance_context, _PROFILE_ROLES


def accountability_feedback_from_result(
    result: PipelineResult, *, success: bool
) -> list[dict[str, Any]]:
    profile = str((result.envelope.metadata or {}).get("governance_profile") or "").lower()
    # Generate feedback for any profile that has a registered role set.
    # Profiles not in _PROFILE_ROLES (e.g. bare "neutral") produce no feedback
    # because there are no named roles to attribute accountability to.
    if profile not in _PROFILE_ROLES or result.plan is None:
        return []

    profile_role_set: frozenset[str] = frozenset(_PROFILE_ROLES[profile])

    roles = [
        str(step.inputs.get("governance_role") or "")
        for step in result.plan.steps
        if step.inputs.get("governance_role")
    ]
    unique_roles = list(dict.fromkeys(roles))
    if not unique_roles:
        return []

    def _has_role(name: str) -> bool:
        return name in profile_role_set

    entries: list[dict[str, Any]] = []
    if success:
        for role in unique_roles:
            entries.append(
                {
                    "role": role,
                    "delta": ACCOUNTABILITY_CONFIG.success_role_delta,
                    "incidents": 0,
                    "reason": "successful_delivery",
                }
            )
        # Audit role bonus — only if the profile defines an "Inspector General"
        # equivalent; otherwise skip rather than attributing to a missing role.
        if _has_role("Inspector General"):
            entries.append(
                {
                    "role": "Inspector General",
                    "delta": ACCOUNTABILITY_CONFIG.success_audit_delta,
                    "incidents": 0,
                    "reason": "post_run_audit_passed",
                }
            )
        return entries

    stage = result.error_stage or "execute"
    if stage == "validate":
        if _has_role("Compliance Counsel"):
            entries.append(
                {
                    "role": "Compliance Counsel",
                    "delta": ACCOUNTABILITY_CONFIG.validate_compliance_delta,
                    "incidents": 0,
                    "reason": "caught_risk",
                }
            )
        if _has_role("Judicial Review Board"):
            entries.append(
                {
                    "role": "Judicial Review Board",
                    "delta": ACCOUNTABILITY_CONFIG.validate_review_delta,
                    "incidents": 0,
                    "reason": "independent_review",
                }
            )
        if _has_role("Policy Drafter"):
            entries.append(
                {
                    "role": "Policy Drafter",
                    "delta": ACCOUNTABILITY_CONFIG.validate_drafter_delta,
                    "incidents": 1,
                    "reason": "draft_quality_issue",
                }
            )
    elif stage == "execute":
        if _has_role("Executive Dispatch"):
            entries.append(
                {
                    "role": "Executive Dispatch",
                    "delta": ACCOUNTABILITY_CONFIG.execute_dispatch_delta,
                    "incidents": 1,
                    "reason": "execution_incident",
                }
            )
        entries.append(
            {
                "role": unique_roles[0],
                "delta": ACCOUNTABILITY_CONFIG.execute_lead_delta,
                "incidents": 1,
                "reason": "leading_role_incident",
            }
        )
    else:
        if _has_role("Intake Clerk"):
            entries.append(
                {
                    "role": "Intake Clerk",
                    "delta": ACCOUNTABILITY_CONFIG.fallback_intake_delta,
                    "incidents": 1,
                    "reason": "upstream_issue",
                }
            )
    return entries


def merge_accountability_feedback(
    metadata: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    max_items: int = ACCOUNTABILITY_CONFIG.default_feedback_max_items,
) -> dict[str, Any]:
    out = dict(metadata or {})
    existing = out.get("accountability_feedback")
    if not isinstance(existing, list):
        existing = []
    normalized = [_normalize_feedback_entry(e) for e in entries if isinstance(e, dict)]
    merged = [*existing, *normalized]
    out["accountability_feedback"] = merged[-max_items:]
    return out


def governance_loop_snapshot(
    metadata: dict[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    ctx = build_governance_context(metadata)
    return {
        "profile": ctx.profile,
        "governance_level": ctx.level,
        "role_weights": ctx.role_weights,
        "latest_feedback": entries,
    }


def _normalize_feedback_entry(entry: dict[str, Any]) -> dict[str, Any]:
    role = str(entry.get("role") or "").strip()
    reason = str(entry.get("reason") or "").strip()[: ACCOUNTABILITY_CONFIG.reason_max_length]
    try:
        delta = float(entry.get("delta", 0.0))
    except (TypeError, ValueError):
        delta = 0.0
    try:
        incidents = int(float(entry.get("incidents", 0)))
    except (TypeError, ValueError):
        incidents = 0
    observed_at = entry.get("observed_at")
    if isinstance(observed_at, str) and observed_at.strip():
        ts = observed_at.strip()
    else:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "role": role,
        "delta": max(ACCOUNTABILITY_CONFIG.delta_min, min(ACCOUNTABILITY_CONFIG.delta_max, delta)),
        "incidents": max(0, incidents),
        "reason": reason,
        "observed_at": ts,
    }

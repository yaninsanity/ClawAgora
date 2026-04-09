"""Governance leaderboard and budget utilities.

Extracted from views.py so that both the HTTP layer (views.py) and the
async worker layer (jobs.py) can import without the worker layer depending on
Django's HTTP view classes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

# Snapshot narrative strings — single source of truth used by views, jobs, and
# the snapshot payloads stored in GovernanceSnapshot.
LEADERBOARD_NARRATIVE = "Constitutional Governance Leaderboard"
DASHBOARD_NARRATIVE = "Agora Governance Operations Panel"

# Per-profile display titles for the governance status view.
# Register additional profiles via register_profile_title().
_PROFILE_TITLES: dict[str, str] = {
    "constitutional_western": "Constitutional Governance Loop",
}
_DEFAULT_PROFILE_TITLE = "Governance Loop"


def register_profile_title(profile: str, title: str) -> None:
    """Register a display title for a governance profile."""
    _PROFILE_TITLES[profile.strip().lower()] = title


def profile_title(profile: str) -> str:
    """Return the display title for *profile*, falling back to a generic label."""
    return _PROFILE_TITLES.get(profile.strip().lower(), _DEFAULT_PROFILE_TITLE)


# Per-level display metadata for governance profile cards.
# Register additional levels via register_level_meta().
_LEVEL_META: dict[str, dict[str, str]] = {
    "minimal":  {"latency_estimate": "low",    "risk_control": "baseline",    "cost_estimate": "low"},
    "balanced": {"latency_estimate": "medium", "risk_control": "strong",      "cost_estimate": "medium"},
    "strict":   {"latency_estimate": "high",   "risk_control": "very_strong", "cost_estimate": "high"},
}
_DEFAULT_LEVEL_META: dict[str, str] = {
    "latency_estimate": "medium",
    "risk_control": "strong",
    "cost_estimate": "medium",
}


def register_level_meta(level: str, latency_estimate: str, risk_control: str, cost_estimate: str) -> None:
    """Register display metadata for a governance level (used in profile cards)."""
    _LEVEL_META[level.strip().lower()] = {
        "latency_estimate": latency_estimate,
        "risk_control": risk_control,
        "cost_estimate": cost_estimate,
    }


def level_meta(level: str) -> dict[str, str]:
    """Return display metadata for *level*, falling back to neutral defaults."""
    return _LEVEL_META.get(level.strip().lower(), _DEFAULT_LEVEL_META)


def leaderboard_reason(success_rate: float, incident_rate: float, avg_delta: float) -> str:
    """Return a human-readable reason string for a role's leaderboard position."""
    if incident_rate >= 1.0:
        return "High incident density; reduce authority weight and increase review intensity."
    if success_rate >= 0.8 and avg_delta > 0:
        return (
            "Strong outcomes with positive accountability drift; increase execution priority."
        )
    if avg_delta < 0:
        return "Negative accountability trend; keep role active but with tighter guardrails."
    return "Stable profile; keep near-neutral weight and continue monitoring."


def _feedback_decay(*, now, task_time) -> float:
    age_days = max((now - task_time).total_seconds() / timedelta(days=1).total_seconds(), 0.0)
    return 0.5 ** (age_days / 30.0)


def leaderboard_rows(profile: str, *, scan_limit: int = 500) -> tuple[list[dict], int]:
    """Aggregate per-role governance stats across recent tasks for *profile*.

    Returns ``(ranked_rows, tasks_scanned)``.  Rows are sorted by descending
    efficiency score, then recommended weight, then ascending cycle time.
    """
    from orchestration.app_settings import governance_leaderboard_config, governance_runtime_config
    from orchestration.models import Task

    runtime_cfg = governance_runtime_config()
    scan_limit = max(scan_limit, 1) if scan_limit else runtime_cfg.leaderboard_scan_limit
    tasks = (
        Task.objects.filter(metadata__governance_profile=profile)
        .order_by("-updated_at")
        .only("id", "status", "metadata", "created_at", "updated_at")
    )
    role_stats: dict[str, dict] = defaultdict(
        lambda: {
            "feedback_count": 0,
            "tasks_touched": set(),
            "delta_total": 0.0,
            "incident_total": 0,
            "success_count": 0,
            "failure_count": 0,
            "cycle_seconds_total": 0.0,
        }
    )
    scanned = 0
    now = timezone.now()
    for task in tasks[:scan_limit].iterator(chunk_size=100):
        scanned += 1
        metadata = task.metadata or {}
        feedback = metadata.get("accountability_feedback")
        if not isinstance(feedback, list):
            continue
        cycle_seconds = max((task.updated_at - task.created_at).total_seconds(), 0.0)
        decay = _feedback_decay(now=now, task_time=task.updated_at)
        latest_by_role: dict[str, dict] = {}
        for item in feedback:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            if not role:
                continue
            latest_by_role[role] = item
        for role, item in latest_by_role.items():
            st = role_stats[role]
            st["feedback_count"] += 1
            st["tasks_touched"].add(str(task.id))
            st["delta_total"] += float(item.get("delta", 0.0) or 0.0) * decay
            st["incident_total"] += int(float(item.get("incidents", 0) or 0.0))
            st["cycle_seconds_total"] += cycle_seconds
            if task.status == Task.Status.COMPLETED:
                st["success_count"] += 1
            elif task.status == Task.Status.FAILED:
                st["failure_count"] += 1
    cfg = governance_leaderboard_config()
    ranked = []
    for role, st in role_stats.items():
        feedback_count = st["feedback_count"] or 1
        touched = len(st["tasks_touched"]) or 1
        success = st["success_count"]
        failure = st["failure_count"]
        incident_rate = st["incident_total"] / feedback_count
        success_rate = success / max(success + failure, 1)
        avg_cycle_seconds = st["cycle_seconds_total"] / feedback_count
        avg_delta = st["delta_total"] / feedback_count
        suggested = (
            1.0
            + (avg_delta * cfg.delta_gain)
            + (success_rate * cfg.success_gain)
            - (incident_rate * cfg.incident_penalty)
        )
        suggested = round(
            max(cfg.recommended_weight_min, min(cfg.recommended_weight_max, suggested)), 4
        )
        efficiency_score = round(
            max(
                0.0,
                min(
                    1.0,
                    (success_rate * cfg.efficiency_success_gain)
                    + ((1.0 / (1.0 + incident_rate)) * cfg.efficiency_incident_gain),
                ),
            ),
            4,
        )
        ranked.append(
            {
                "role": role,
                "feedback_count": feedback_count,
                "tasks_touched": touched,
                "success_count": success,
                "failure_count": failure,
                "incident_total": st["incident_total"],
                "avg_delta": round(avg_delta, 4),
                "avg_cycle_seconds": round(avg_cycle_seconds, 2),
                "efficiency_score": efficiency_score,
                "recommended_weight": suggested,
                "reason": leaderboard_reason(success_rate, incident_rate, avg_delta),
            }
        )
    ranked.sort(
        key=lambda x: (
            -x["efficiency_score"],
            -x["recommended_weight"],
            x["avg_cycle_seconds"],
            x["role"],
        )
    )
    return ranked, scanned


def today_used_budget(profile: str) -> dict[str, float]:
    """Return per-role weight-change totals applied today for *profile*."""
    from orchestration.models import GovernanceProfileRevision

    day_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    revisions = GovernanceProfileRevision.objects.filter(
        profile=profile,
        created_at__gte=day_start,
    ).only("change_set")
    used: dict[str, float] = defaultdict(float)
    for rev in revisions:
        if not isinstance(rev.change_set, dict):
            continue
        for role, delta in rev.change_set.items():
            try:
                used[str(role)] += abs(float(delta))
            except (TypeError, ValueError):
                continue
    return dict(used)

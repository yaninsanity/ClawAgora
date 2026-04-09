from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.utils import timezone

from orchestration.logging_support import task_id_var

logger = logging.getLogger(__name__)


def run_task_job(task_id: str) -> None:
    from orchestration.api_exceptions import TaskConflict, TaskInProgress
    from orchestration.models import Task
    from orchestration.services import get_orchestration_service

    tok = task_id_var.set(task_id)
    try:
        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            logger.warning("worker_task_missing task_id=%s", task_id)
            return

        logger.info("worker_run_start")
        try:
            get_orchestration_service().run_task(task)
        except TaskConflict as exc:
            logger.info(
                "worker_idempotent_skip detail=%s",
                getattr(exc, "detail", exc),
            )
        except TaskInProgress:
            logger.info("worker_idempotent_skip detail=running")
        except Exception:
            logger.exception("worker_run_failed")
            raise
        else:
            logger.info("worker_run_done")
    finally:
        task_id_var.reset(tok)


def refresh_governance_snapshots_job() -> int:
    """Build leaderboard/dashboard snapshots for active governance profiles."""
    from orchestration.leaderboard import leaderboard_rows, today_used_budget, LEADERBOARD_NARRATIVE
    from orchestration.models import GovernanceProfileState, GovernanceSnapshot, Task
    from clawagora.governance.profile import resolve_governance_level
    from orchestration.app_settings import (
        governance_alert_budget_threshold,
        governance_alert_low_efficiency_threshold,
        governance_daily_budget,
        governance_runtime_config,
    )

    runtime_cfg = governance_runtime_config()
    budget_threshold = governance_alert_budget_threshold()
    efficiency_threshold = governance_alert_low_efficiency_threshold()
    profiles = set(
        Task.objects.exclude(metadata__governance_profile__isnull=True).values_list(
            "metadata__governance_profile", flat=True
        )
    )
    profiles.discard(None)
    written = 0
    for profile_raw in profiles:
        profile = str(profile_raw or "").strip().lower()
        if not profile:
            continue
        ranked, scanned = leaderboard_rows(profile, scan_limit=runtime_cfg.leaderboard_scan_limit)
        baseline = GovernanceProfileState.objects.filter(profile=profile).first()
        GovernanceSnapshot.objects.update_or_create(
            profile=profile,
            governance_level="",
            snapshot_type="leaderboard",
            defaults={
                "payload": {
                    "profile": profile,
                    "narrative": LEADERBOARD_NARRATIVE,
                    "tasks_scanned": scanned,
                    "roles_ranked": len(ranked),
                    "applied_baseline": (baseline.baseline_weights if baseline else {}),
                    "roles": ranked,
                }
            },
        )
        written += 1

        level = resolve_governance_level(
            {
                "governance_level": baseline.default_level
                if baseline and baseline.default_level
                else "balanced"
            }
        )
        budget = governance_daily_budget(level)
        used = today_used_budget(profile)
        top = ranked[:10]
        alerts = []
        for role, used_amt in used.items():
            ratio = used_amt / budget if budget > 0 else 1.0
            if ratio >= budget_threshold:
                alerts.append(
                    {"type": "budget_near_exhausted", "role": role, "usage_ratio": round(ratio, 4)}
                )
        for item in top:
            if item["efficiency_score"] < efficiency_threshold:
                alerts.append(
                    {
                        "type": "low_efficiency",
                        "role": item["role"],
                        "efficiency_score": item["efficiency_score"],
                    }
                )
        GovernanceSnapshot.objects.update_or_create(
            profile=profile,
            governance_level=level,
            snapshot_type="dashboard",
            defaults={
                "payload": {
                    "profile": profile,
                    "governance_level": level,
                    "narrative": "Agora Governance Operations Panel",
                    "tasks_scanned": scanned,
                    "daily_budget": round(budget, 4),
                    "daily_budget_used": {k: round(v, 4) for k, v in used.items()},
                    "daily_budget_remaining": {
                        k: round(max(budget - v, 0.0), 4) for k, v in used.items()
                    },
                    "applied_baseline": (baseline.baseline_weights if baseline else {}),
                    "leaderboard_top": top,
                    "alerts": alerts[:25],
                }
            },
        )
        written += 1
    logger.info("governance_snapshots_refreshed count=%s", written)
    return written


def _retry_backoff_sleep(attempt: int, retries: int) -> None:
    if attempt < retries:
        base = 0.05 * (2 ** (attempt - 1))
        time.sleep(base + random.uniform(0.0, 0.03))


def deliver_governance_alerts_job() -> dict:
    """Deliver governance alerts to subscriptions with retry + dead-letter."""
    from orchestration.models import (
        GovernanceAlertDeadLetter,
        GovernanceAlertDelivery,
        GovernanceProfileState,
        GovernanceAlertSubscription,
    )
    from orchestration.leaderboard import leaderboard_rows, today_used_budget
    from clawagora.governance.profile import resolve_governance_level
    from orchestration.app_settings import (
        governance_alert_budget_threshold,
        governance_alert_low_efficiency_threshold,
        governance_alert_max_retries,
        governance_daily_budget,
        governance_runtime_config,
        governance_signing_key,
    )

    retries = governance_alert_max_retries()
    runtime_cfg = governance_runtime_config()
    signing_key = governance_signing_key().encode("utf-8")
    budget_threshold = governance_alert_budget_threshold()
    efficiency_threshold = governance_alert_low_efficiency_threshold()
    delivered = 0
    dead_lettered = 0
    failed = 0
    subs = GovernanceAlertSubscription.objects.filter(enabled=True)
    for sub in subs:
        profile = sub.profile
        ranked, _ = leaderboard_rows(profile, scan_limit=runtime_cfg.alert_scan_limit)
        state = GovernanceProfileState.objects.filter(profile=profile).only("default_level").first()
        level = resolve_governance_level(
            {
                "governance_level": state.default_level
                if state and state.default_level
                else "balanced"
            }
        )
        budget = governance_daily_budget(level)
        used = today_used_budget(profile)
        events = []
        for role, used_amt in used.items():
            ratio = used_amt / budget if budget > 0 else 1.0
            if ratio >= budget_threshold:
                events.append(
                    {
                        "event_type": "budget_near_exhausted",
                        "payload": {
                            "profile": profile,
                            "role": role,
                            "usage_ratio": round(ratio, 4),
                        },
                    }
                )
        for item in ranked[:10]:
            if item["efficiency_score"] < efficiency_threshold:
                events.append(
                    {
                        "event_type": "low_efficiency",
                        "payload": {
                            "profile": profile,
                            "role": item["role"],
                            "efficiency_score": item["efficiency_score"],
                        },
                    }
                )
        allowed = set(sub.event_types or [])
        for ev in events:
            if allowed and ev["event_type"] not in allowed:
                continue
            body = json.dumps(ev["payload"], ensure_ascii=False).encode("utf-8")
            signature = hmac.new(signing_key, body, hashlib.sha256).hexdigest()
            ok = False
            last_err = ""
            for attempt in range(1, retries + 1):
                try:
                    req = Request(
                        sub.target,
                        data=body,
                        method="POST",
                        headers={
                            "Content-Type": "application/json",
                            "X-ClawAgora-Signature": signature,
                            "X-ClawAgora-Event": ev["event_type"],
                        },
                    )
                    with urlopen(req, timeout=5) as resp:  # noqa: S310
                        status = int(getattr(resp, "status", 200))
                    if 200 <= status < 300:
                        GovernanceAlertDelivery.objects.create(
                            subscription=sub,
                            event_type=ev["event_type"],
                            payload=ev["payload"],
                            attempt=attempt,
                            status="delivered",
                            delivered_at=timezone.now(),
                        )
                        delivered += 1
                        ok = True
                        break
                    last_err = f"http_{status}"
                    GovernanceAlertDelivery.objects.create(
                        subscription=sub,
                        event_type=ev["event_type"],
                        payload=ev["payload"],
                        attempt=attempt,
                        status="failed",
                        error=last_err,
                    )
                    _retry_backoff_sleep(attempt, retries)
                except (HTTPError, URLError, TimeoutError, OSError) as exc:
                    last_err = str(exc)[:512]
                    GovernanceAlertDelivery.objects.create(
                        subscription=sub,
                        event_type=ev["event_type"],
                        payload=ev["payload"],
                        attempt=attempt,
                        status="failed",
                        error=last_err,
                    )
                    _retry_backoff_sleep(attempt, retries)
            if not ok:
                failed += 1
                GovernanceAlertDeadLetter.objects.create(
                    subscription=sub,
                    event_type=ev["event_type"],
                    payload=ev["payload"],
                    attempts=retries,
                    last_error=last_err,
                )
                dead_lettered += 1
    out = {"delivered": delivered, "failed": failed, "dead_lettered": dead_lettered}
    logger.info("governance_alert_delivery_result %s", out)
    return out


def replay_governance_dead_letters_job(
    *,
    limit: int = 50,
    profile: str | None = None,
    event_type: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Replay unresolved dead letters with single-attempt delivery."""
    from orchestration.models import GovernanceAlertDeadLetter
    from orchestration.app_settings import governance_runtime_config, governance_signing_key

    qs = GovernanceAlertDeadLetter.objects.filter(resolved=False).select_related("subscription")
    runtime_cfg = governance_runtime_config()
    profile_norm = str(profile or "").strip().lower()
    event_norm = str(event_type or "").strip().lower()
    if profile_norm:
        qs = qs.filter(subscription__profile=profile_norm)
    if event_norm:
        qs = qs.filter(event_type=event_norm)
    picked = list(qs.order_by("created_at")[:limit])
    replayed = resolved = failed = skipped = 0
    signing_key = governance_signing_key().encode("utf-8")
    preview = []
    for dlq in picked:
        replayed += 1
        preview.append(
            {
                "id": dlq.id,
                "profile": dlq.subscription.profile,
                "event_type": dlq.event_type,
                "target": dlq.subscription.target,
                "attempts": dlq.attempts,
                "replay_count": dlq.replay_count,
                "subscription_enabled": dlq.subscription.enabled,
            }
        )
        if dry_run:
            continue
        if not dlq.subscription.enabled:
            skipped += 1
            continue
        payload = json.dumps(dlq.payload, ensure_ascii=False).encode("utf-8")
        signature = hmac.new(signing_key, payload, hashlib.sha256).hexdigest()
        try:
            req = Request(
                dlq.subscription.target,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-ClawAgora-Signature": signature,
                    "X-ClawAgora-Event": dlq.event_type,
                    "X-ClawAgora-Replay": "1",
                },
            )
            with urlopen(req, timeout=5) as resp:  # noqa: S310
                status = int(getattr(resp, "status", 200))
            if 200 <= status < 300:
                dlq.resolved = True
                dlq.replayed_at = timezone.now()
                dlq.replay_count += 1
                dlq.last_error = ""
                dlq.save(update_fields=["resolved", "replayed_at", "replay_count", "last_error"])
                resolved += 1
            else:
                dlq.replay_count += 1
                dlq.last_error = f"http_{status}"
                dlq.replayed_at = timezone.now()
                dlq.save(update_fields=["replay_count", "last_error", "replayed_at"])
                failed += 1
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            dlq.replay_count += 1
            dlq.last_error = str(exc)[:512]
            dlq.replayed_at = timezone.now()
            dlq.save(update_fields=["replay_count", "last_error", "replayed_at"])
            failed += 1
    out = {
        "replayed": replayed,
        "resolved": resolved,
        "failed": failed,
        "skipped_disabled": skipped,
        "dry_run": dry_run,
        "profile": profile_norm or None,
        "event_type": event_norm or None,
        "items": preview[: runtime_cfg.replay_preview_max_items],
    }
    logger.info("governance_deadletter_replay_result %s", out)
    return out

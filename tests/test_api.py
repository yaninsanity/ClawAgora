from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import Client, override_settings

from orchestration.api_exceptions import TaskConflict
from orchestration.models import ApprovalRequest, PolicyDraft, Task
from orchestration.services import (
    OrchestrationService,
    get_orchestration_service,
    set_orchestration_service,
)


@pytest.mark.django_db
def test_create_task_returns_timeline_receipt_and_terminal():
    c = Client()
    resp = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Add unit tests for the payment module.", "metadata": {}},
        content_type="application/json",
    )
    assert resp.status_code == 201
    payload = resp.json()
    task_id = payload["id"]
    assert payload["external_ref"] == task_id
    assert payload["receipt"] is not None
    assert payload["receipt"]["body_hash"]
    assert payload["run_attempt"] == 1

    tl = c.get(f"/api/v1/tasks/{task_id}/timeline/")
    assert tl.status_code == 200
    events = tl.json()
    assert any(e.get("phase") == "terminal" and e.get("kind") == "completed" for e in events)

    rc = c.get(f"/api/v1/tasks/{task_id}/receipt/")
    assert rc.status_code == 200
    assert rc.json()["body_hash"] == payload["receipt"]["body_hash"]


@pytest.mark.django_db
def test_health():
    c = Client()
    r = c.get("/api/v1/health/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "cache" in body
    assert body["cache"]["backend"] in ("locmem", "redis")
    assert isinstance(body["cache"]["shared"], bool)
    assert "redis" in body


@pytest.mark.django_db
def test_invalid_execution_header_returns_400():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "hello", "metadata": {}},
        content_type="application/json",
        HTTP_X_CLAWAGORA_EXECUTION="invalid-mode",
    )
    assert r.status_code == 400
    envelope = r.json()
    assert envelope.get("status") == 400
    inner = envelope.get("body") or {}
    err = inner.get("X-ClawAgora-Execution") or inner.get("detail")
    assert err is not None
    assert "async" in str(err).lower() and "sync" in str(err).lower()


@pytest.mark.django_db
def test_idempotency_key_returns_same_task():
    c = Client()
    headers = {"HTTP_IDEMPOTENCY_KEY": "idem-test-1"}
    body = {"input_text": "Idempotent request body.", "metadata": {}}
    r1 = c.post("/api/v1/tasks/", data=body, content_type="application/json", **headers)
    r2 = c.post("/api/v1/tasks/", data=body, content_type="application/json", **headers)
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.django_db
def test_retry_after_validation_failure():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "   ", "metadata": {}},
        content_type="application/json",
    )
    assert r.status_code == 201
    tid = r.json()["id"]
    assert r.json()["status"] == "failed"
    r2 = c.post(f"/api/v1/tasks/{tid}/retry/", content_type="application/json")
    assert r2.status_code == 200
    assert r2.json()["status"] in ("completed", "failed")


@pytest.mark.django_db
def test_double_run_raises_conflict():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Valid input for pipeline.", "metadata": {}},
        content_type="application/json",
    )
    assert r.status_code == 201
    task = Task.objects.get(pk=r.json()["id"])
    with pytest.raises(TaskConflict):
        get_orchestration_service().run_task(task)


# ---------------------------------------------------------------------------
# Domain executor routing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_engineering_task_uses_coding_executor():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Refactor the authentication API module.", "metadata": {}},
        content_type="application/json",
    )
    assert r.status_code == 201
    payload = r.json()
    assert payload["status"] == "completed"
    # The receipt body should contain output from executor_coding
    receipt_body = payload["receipt"]["body"]
    artifacts = receipt_body.get("artifacts", [])
    executors_used = [a["executor"] for a in artifacts]
    assert "executor_coding" in executors_used


@pytest.mark.django_db
def test_research_task_uses_research_executor():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Summarize the research paper on attention mechanisms.",
            "metadata": {},
        },
        content_type="application/json",
    )
    assert r.status_code == 201
    payload = r.json()
    assert payload["status"] == "completed"
    receipt_body = payload["receipt"]["body"]
    executors_used = [a["executor"] for a in receipt_body.get("artifacts", [])]
    assert "executor_research" in executors_used


# ---------------------------------------------------------------------------
# Cancel endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cancel_queued_task():
    task = Task.objects.create(
        input_text="Cancel me before execution.",
        metadata={},
        status=Task.Status.QUEUED,
    )
    c = Client()
    r = c.post(f"/api/v1/tasks/{task.id}/cancel/", content_type="application/json")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    task.refresh_from_db()
    assert task.status == Task.Status.CANCELLED
    assert task.error_code == "cancelled"


@pytest.mark.django_db
def test_cancel_received_task():
    task = Task.objects.create(
        input_text="Cancel me too.",
        metadata={},
        status=Task.Status.RECEIVED,
    )
    c = Client()
    r = c.post(f"/api/v1/tasks/{task.id}/cancel/", content_type="application/json")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


@pytest.mark.django_db
def test_cancel_completed_task_returns_409():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Run to completion first.", "metadata": {}},
        content_type="application/json",
    )
    assert r.status_code == 201
    assert r.json()["status"] == "completed"
    r2 = c.post(f"/api/v1/tasks/{r.json()['id']}/cancel/", content_type="application/json")
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Replay endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_replay_events_mode():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Replay this task.", "metadata": {}},
        content_type="application/json",
    )
    assert r.status_code == 201
    task_id = r.json()["id"]

    replay = c.get(f"/api/v1/tasks/{task_id}/replay/")
    assert replay.status_code == 200
    body = replay.json()
    assert body["mode"] == "events"
    assert body["task_id"] == task_id
    assert len(body["records"]) > 0
    phases = {rec["phase"] for rec in body["records"]}
    assert "intake" in phases
    assert "terminal" in phases


@pytest.mark.django_db
def test_replay_decisions_mode():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Replay decisions only.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]

    replay = c.get(f"/api/v1/tasks/{task_id}/replay/?mode=decisions")
    assert replay.status_code == 200
    body = replay.json()
    assert body["mode"] == "decisions"
    phases = {rec["phase"] for rec in body["records"]}
    # decisions mode: only classify, validate, terminal
    assert phases.issubset({"classify", "validate", "terminal"})
    # intake and plan events must be excluded
    assert "intake" not in phases
    assert "plan" not in phases


@pytest.mark.django_db
def test_replay_invalid_mode_returns_400():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Any task.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]
    replay = c.get(f"/api/v1/tasks/{task_id}/replay/?mode=invalid")
    assert replay.status_code == 400


# ---------------------------------------------------------------------------
# Trust score + optimization in receipt
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_receipt_contains_phase4_governance_data():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Add unit tests for the login flow.", "metadata": {}},
        content_type="application/json",
    )
    assert r.status_code == 201
    receipt_body = r.json()["receipt"]["body"]

    # trust_score
    assert "trust_score" in receipt_body
    ts = receipt_body["trust_score"]
    assert 0.0 <= ts["value"] <= 1.0
    assert len(ts["reasons"]) > 0

    # optimization
    assert "optimization" in receipt_body
    opt = receipt_body["optimization"]
    assert "task_id" in opt
    assert isinstance(opt["items"], list)

    # rollback_plan
    assert "rollback_plan" in receipt_body
    rp = receipt_body["rollback_plan"]
    assert isinstance(rp["steps"], list)
    assert len(rp["steps"]) > 0  # at least one completed step


@pytest.mark.django_db
def test_constitutional_profile_writes_governance_feedback_loop():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Design a deployment policy and execute rollout checklist.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    assert r.status_code == 201
    payload = r.json()
    feedback = payload["metadata"].get("accountability_feedback") or []
    assert feedback, payload["metadata"]
    assert any(item.get("role") == "Inspector General" for item in feedback)

    loop = payload["receipt"]["body"].get("governance_loop") or {}
    assert loop.get("profile") == "constitutional_western"
    assert "role_weights" in loop
    assert "latest_feedback" in loop
    assert "prompt_trace" in loop
    assert "classify" in loop["prompt_trace"]
    assert "synthesize" in loop["prompt_trace"]
    receipt_prompt_trace = payload["receipt"]["body"].get("prompt_trace") or {}
    assert "classify" in receipt_prompt_trace
    assert "synthesize" in receipt_prompt_trace
    tl = c.get(f"/api/v1/tasks/{payload['id']}/timeline/")
    assert tl.status_code == 200
    governance_events = [e for e in tl.json() if e["phase"] == "governance"]
    assert governance_events
    assert "prompt_trace" in (governance_events[-1].get("payload") or {})


@pytest.mark.django_db
def test_constitutional_profile_reuses_accountability_feedback_weights():
    c = Client()
    seed_feedback = [
        {"role": "Policy Drafter", "delta": 0.5, "incidents": 0},
        {"role": "Intake Clerk", "delta": -0.2, "incidents": 1},
    ]
    r = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Draft policy for incident response and assign execution.",
            "metadata": {
                "governance_profile": "constitutional_western",
                "accountability_feedback": seed_feedback,
            },
        },
        content_type="application/json",
    )
    assert r.status_code == 201
    plan = r.json()["plan"] or {}
    steps = plan.get("steps") or []
    assert steps
    weights = [float(s["inputs"]["governance_weight"]) for s in steps]
    assert any(w != 1.0 for w in weights)


@pytest.mark.django_db
def test_governance_feedback_api_appends_feedback_and_event():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Prepare policy execution baseline.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    r = c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": task_id,
            "source": "inspector_console",
            "entries": [
                {
                    "role": "Judicial Review Board",
                    "delta": 0.2,
                    "incidents": 0,
                    "reason": "strong review quality",
                }
            ],
        },
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.json()
    feedback = body["metadata"].get("accountability_feedback") or []
    assert any(x.get("reason") == "strong review quality" for x in feedback)

    timeline = c.get(f"/api/v1/tasks/{task_id}/timeline/")
    assert timeline.status_code == 200
    gov_events = [e for e in timeline.json() if e["phase"] == "governance"]
    assert gov_events
    assert any(e["kind"] == "manual_feedback" for e in gov_events)


@pytest.mark.django_db
def test_governance_feedback_rejects_unknown_role_for_constitutional_profile():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Role whitelist validation.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    task_id = created.json()["id"]
    r = c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": task_id,
            "entries": [{"role": "Unknown Ministry", "delta": 0.1, "incidents": 0}],
        },
        content_type="application/json",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_governance_status_endpoint_returns_loop_and_efficiency():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Constitutional profile task with governance telemetry.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    r = c.get(f"/api/v1/tasks/{task_id}/governance/")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["profile"] == "constitutional_western"
    assert body["governance_level"] == "balanced"
    assert "narrative_stage" in body
    assert "role_weights" in body and isinstance(body["role_weights"], dict)
    eff = body["efficiency"]
    assert "cycle_seconds" in eff
    assert "governance_event_ratio" in eff
    assert isinstance(body["governance_timeline"], list)


@pytest.mark.django_db
def test_governance_leaderboard_returns_ranked_roles_and_recommendations():
    c = Client()
    for text in (
        "Constitutional governance task A",
        "Constitutional governance task B",
        "Constitutional governance task C",
    ):
        created = c.post(
            "/api/v1/tasks/",
            data={
                "input_text": text,
                "metadata": {"governance_profile": "constitutional_western"},
            },
            content_type="application/json",
        )
        assert created.status_code == 201
        tid = created.json()["id"]
        c.post(
            "/api/v1/governance/feedback/",
            data={
                "task_id": tid,
                "source": "inspector_console",
                "entries": [
                    {"role": "Judicial Review Board", "delta": 0.18, "incidents": 0},
                    {"role": "Executive Dispatch", "delta": -0.05, "incidents": 1},
                ],
            },
            content_type="application/json",
        )

    r = c.get("/api/v1/governance/leaderboard/?profile=constitutional_western&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "constitutional_western"
    assert body["roles_ranked"] >= 2
    roles = body["roles"]
    assert roles
    assert all("recommended_weight" in item for item in roles)
    assert all("efficiency_score" in item for item in roles)
    assert all("reason" in item for item in roles)


@pytest.mark.django_db
def test_governance_leaderboard_rejects_bad_limit():
    c = Client()
    r = c.get("/api/v1/governance/leaderboard/?limit=bad")
    assert r.status_code == 400


@pytest.mark.django_db
def test_apply_recommendations_persists_baseline_and_exposes_in_leaderboard():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Baseline recommendation source task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [
                {"role": "Judicial Review Board", "delta": 0.22, "incidents": 0},
                {"role": "Executive Dispatch", "delta": -0.04, "incidents": 1},
            ],
        },
        content_type="application/json",
    )
    applied = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "limit": 5, "source": "ops_auto"},
        content_type="application/json",
    )
    assert applied.status_code == 200
    payload = applied.json()
    assert payload["updated"] is True
    assert payload["roles_applied"] >= 1
    assert "Judicial Review Board" in payload["baseline_weights"]

    board = c.get("/api/v1/governance/leaderboard/?profile=constitutional_western")
    assert board.status_code == 200
    assert "applied_baseline" in board.json()
    assert "Judicial Review Board" in board.json()["applied_baseline"]


@pytest.mark.django_db
def test_apply_recommendations_affects_next_task_planner_weights():
    c = Client()
    seed = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Seed constitutional telemetry.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    seed_id = seed.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": seed_id,
            "entries": [{"role": "Policy Drafter", "delta": 0.4, "incidents": 0}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "limit": 3},
        content_type="application/json",
    )

    nxt = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Next task should inherit baseline weights.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    assert nxt.status_code == 201
    plan = nxt.json()["plan"] or {}
    steps = plan.get("steps") or []
    assert steps
    weights = [float(s["inputs"]["governance_weight"]) for s in steps]
    assert any(w != 1.0 for w in weights)


@pytest.mark.django_db
@override_settings(CLAWAGORA_GOVERNANCE_KEY="gov-secret")
def test_governance_write_endpoints_require_governance_key():
    c = Client()
    no_key = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western"},
        content_type="application/json",
    )
    assert no_key.status_code == 403
    good = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "dry_run": True},
        content_type="application/json",
        HTTP_X_GOVERNANCE_KEY="gov-secret",
    )
    assert good.status_code == 200


@pytest.mark.django_db
def test_apply_recommendations_dry_run_returns_diff_only():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Dry-run candidate task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    task_id = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": task_id,
            "entries": [{"role": "Policy Drafter", "delta": 0.2, "incidents": 0}],
        },
        content_type="application/json",
    )
    r = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "dry_run": True},
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["updated"] is False
    assert body["governance_level"] == "balanced"
    assert "diff" in body


@pytest.mark.django_db
@override_settings(CLAWAGORA_GOVERNANCE_DAILY_BUDGET_STRICT_BPS=200)
def test_apply_recommendations_strict_level_limits_step_change():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Strict-level baseline smoothing task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    task_id = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": task_id,
            "entries": [{"role": "Policy Drafter", "delta": 0.9, "incidents": 0}],
        },
        content_type="application/json",
    )
    r = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "strict", "limit": 3},
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["governance_level"] == "strict"
    w = float(body["baseline_weights"].get("Policy Drafter", 1.0))
    assert 1.0 <= w <= 1.02
    assert body["daily_budget"] == 0.02


@pytest.mark.django_db
def test_governance_rollback_restores_previous_baseline():
    c = Client()
    seed = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Rollback seed task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = seed.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Policy Drafter", "delta": 0.3, "incidents": 0}],
        },
        content_type="application/json",
    )
    first = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "limit": 2},
        content_type="application/json",
    ).json()["baseline_weights"]
    # Change recommendations by adding adverse feedback and applying again.
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Policy Drafter", "delta": -0.3, "incidents": 2}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "limit": 2},
        content_type="application/json",
    )
    rolled = c.post(
        "/api/v1/governance/rollback/",
        data={"profile": "constitutional_western"},
        content_type="application/json",
    )
    assert rolled.status_code == 200
    assert rolled.json()["rolled_back"] is True
    assert rolled.json()["baseline_weights"] == first


@pytest.mark.django_db
@override_settings(CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS=100)
def test_daily_budget_caps_multiple_applies_same_day():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Daily budget cap baseline task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Policy Drafter", "delta": 0.8, "incidents": 0}],
        },
        content_type="application/json",
    )
    first = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "balanced", "limit": 2},
        content_type="application/json",
    )
    w1 = float(first.json()["baseline_weights"].get("Policy Drafter", 1.0))
    second = c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "balanced", "limit": 2},
        content_type="application/json",
    )
    w2 = float(second.json()["baseline_weights"].get("Policy Drafter", 1.0))
    assert second.status_code == 200
    assert abs(w2 - w1) <= 1e-6


@pytest.mark.django_db
def test_governance_dashboard_returns_budget_and_alerts():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Dashboard metrics seed task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Executive Dispatch", "delta": -0.2, "incidents": 2}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "strict"},
        content_type="application/json",
    )
    r = c.get(
        "/api/v1/governance/dashboard/?profile=constitutional_western&governance_level=strict"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "constitutional_western"
    assert body["governance_level"] == "strict"
    assert "daily_budget" in body
    assert "daily_budget_used" in body
    assert "leaderboard_top" in body
    assert isinstance(body["alerts"], list)


@pytest.mark.django_db
def test_governance_profiles_select_level_applies_to_new_tasks():
    c = Client()
    sel = c.post(
        "/api/v1/governance/profiles/",
        data={"profile": "constitutional_western", "level": "strict"},
        content_type="application/json",
    )
    assert sel.status_code == 200
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Profile selected level inheritance.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    assert created.json()["metadata"]["governance_level"] == "strict"


@pytest.mark.django_db
def test_governance_history_and_forecast_endpoints():
    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "History and forecast baseline seed.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Policy Drafter", "delta": 0.25, "incidents": 0}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={
            "profile": "constitutional_western",
            "reason": "Weekly governance tuning",
            "evidence_rows": [{"role": "Policy Drafter", "signal": "high quality"}],
        },
        content_type="application/json",
    )
    h = c.get("/api/v1/governance/leaderboard/history/?profile=constitutional_western")
    assert h.status_code == 200
    assert len(h.json()["history"]) >= 1
    f = c.get("/api/v1/governance/budget/forecast/?profile=constitutional_western")
    assert f.status_code == 200
    assert "forecast" in f.json()


@pytest.mark.django_db
def test_governance_alert_subscription_crud_basic():
    c = Client()
    created = c.post(
        "/api/v1/governance/alerts/subscriptions/",
        data={
            "profile": "constitutional_western",
            "channel": "webhook",
            "target": "https://example.com/hook",
            "event_types": ["budget_near_exhausted"],
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    listed = c.get("/api/v1/governance/alerts/subscriptions/?profile=constitutional_western")
    assert listed.status_code == 200
    assert any(x["channel"] == "webhook" for x in listed.json())


@pytest.mark.django_db
def test_governance_worker_refreshes_snapshots():
    c = Client()
    c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Snapshot seed task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    call_command("clawagora_governance_worker", refresh_snapshots=True)
    board = c.get("/api/v1/governance/leaderboard/?profile=constitutional_western")
    assert board.status_code == 200
    dash = c.get("/api/v1/governance/dashboard/?profile=constitutional_western")
    assert dash.status_code == 200


@pytest.mark.django_db
@override_settings(CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS=1)
def test_governance_worker_dead_letters_failed_delivery():
    from orchestration.models import GovernanceAlertDeadLetter

    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Dead letter seed task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Executive Dispatch", "delta": -0.4, "incidents": 2}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "balanced"},
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/alerts/subscriptions/",
        data={
            "profile": "constitutional_western",
            "channel": "webhook",
            "target": "http://127.0.0.1:9/fail",
            "event_types": ["low_efficiency", "budget_near_exhausted"],
        },
        content_type="application/json",
    )
    call_command("clawagora_governance_worker", deliver_alerts=True)
    assert GovernanceAlertDeadLetter.objects.exists()


@pytest.mark.django_db
@override_settings(CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS=1)
def test_governance_dead_letter_replay_endpoint_resolves_item():
    from orchestration.models import GovernanceAlertDeadLetter

    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Replay dead letter task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Executive Dispatch", "delta": -0.4, "incidents": 2}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "balanced"},
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/alerts/subscriptions/",
        data={
            "profile": "constitutional_western",
            "channel": "webhook",
            "target": "http://127.0.0.1:9/fail",
            "event_types": ["low_efficiency", "budget_near_exhausted"],
        },
        content_type="application/json",
    )
    call_command("clawagora_governance_worker", deliver_alerts=True)
    assert GovernanceAlertDeadLetter.objects.exists()

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("orchestration.jobs.urlopen", return_value=_Resp()):
        replayed = c.post(
            "/api/v1/governance/dead-letters/replay/",
            data={"limit": 10},
            content_type="application/json",
        )
    assert replayed.status_code == 200
    assert replayed.json()["resolved"] >= 1

    listed = c.get("/api/v1/governance/dead-letters/?profile=constitutional_western")
    assert listed.status_code == 200
    assert any(item["resolved"] is True for item in listed.json())


@pytest.mark.django_db
@override_settings(CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS=1)
def test_governance_dead_letter_replay_supports_profile_filter():
    from orchestration.models import GovernanceAlertDeadLetter

    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Replay profile filter task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Executive Dispatch", "delta": -0.3, "incidents": 2}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "balanced"},
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/alerts/subscriptions/",
        data={
            "profile": "constitutional_western",
            "channel": "webhook",
            "target": "http://127.0.0.1:9/fail",
            "event_types": ["low_efficiency", "budget_near_exhausted"],
        },
        content_type="application/json",
    )
    call_command("clawagora_governance_worker", deliver_alerts=True)
    assert GovernanceAlertDeadLetter.objects.filter(
        subscription__profile="constitutional_western"
    ).exists()

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("orchestration.jobs.urlopen", return_value=_Resp()):
        replayed = c.post(
            "/api/v1/governance/dead-letters/replay/",
            data={"limit": 20, "profile": "constitutional_western", "event_type": "low_efficiency"},
            content_type="application/json",
        )
    assert replayed.status_code == 200
    assert replayed.json()["profile"] == "constitutional_western"
    assert replayed.json()["event_type"] == "low_efficiency"


@pytest.mark.django_db
@override_settings(CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS=1)
def test_governance_dead_letter_replay_dry_run_does_not_mutate():
    from orchestration.models import GovernanceAlertDeadLetter

    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Replay dry run task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Executive Dispatch", "delta": -0.3, "incidents": 2}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "balanced"},
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/alerts/subscriptions/",
        data={
            "profile": "constitutional_western",
            "channel": "webhook",
            "target": "http://127.0.0.1:9/fail",
            "event_types": ["low_efficiency", "budget_near_exhausted"],
        },
        content_type="application/json",
    )
    call_command("clawagora_governance_worker", deliver_alerts=True)
    before = GovernanceAlertDeadLetter.objects.filter(
        subscription__profile="constitutional_western", resolved=False
    ).count()
    assert before >= 1

    replayed = c.post(
        "/api/v1/governance/dead-letters/replay/",
        data={"limit": 20, "profile": "constitutional_western", "dry_run": True},
        content_type="application/json",
    )
    assert replayed.status_code == 200
    body = replayed.json()
    assert body["dry_run"] is True
    assert body["resolved"] == 0
    assert len(body["items"]) >= 1

    after = GovernanceAlertDeadLetter.objects.filter(
        subscription__profile="constitutional_western", resolved=False
    ).count()
    assert after == before


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS=9000,
    CLAWAGORA_GOVERNANCE_DAILY_BUDGET_STRICT_BPS=1,
)
def test_governance_alert_worker_uses_profile_default_level_budget():
    from orchestration.models import GovernanceAlertDeadLetter

    c = Client()
    created = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "Profile-level alert budget test task.",
            "metadata": {"governance_profile": "constitutional_western"},
        },
        content_type="application/json",
    )
    tid = created.json()["id"]
    c.post(
        "/api/v1/governance/feedback/",
        data={
            "task_id": tid,
            "entries": [{"role": "Executive Dispatch", "delta": -0.3, "incidents": 2}],
        },
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/apply-recommendations/",
        data={"profile": "constitutional_western", "governance_level": "balanced"},
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/profiles/",
        data={"profile": "constitutional_western", "level": "strict"},
        content_type="application/json",
    )
    c.post(
        "/api/v1/governance/alerts/subscriptions/",
        data={
            "profile": "constitutional_western",
            "channel": "webhook",
            "target": "http://127.0.0.1:9/fail",
            "event_types": ["budget_near_exhausted"],
        },
        content_type="application/json",
    )
    call_command("clawagora_governance_worker", deliver_alerts=True)
    assert GovernanceAlertDeadLetter.objects.filter(
        subscription__profile="constitutional_western",
        event_type="budget_near_exhausted",
    ).exists()


# ---------------------------------------------------------------------------
# Policy Draft CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_policy_draft_create_and_list():
    c = Client()
    r = c.post(
        "/api/v1/policies/",
        data={"name": "safety-v1", "content": {"deny_terms": ["secret", "password"]}},
        content_type="application/json",
    )
    assert r.status_code == 201
    draft = r.json()
    assert draft["name"] == "safety-v1"
    assert draft["content"]["deny_terms"] == ["secret", "password"]

    r2 = c.get("/api/v1/policies/")
    assert r2.status_code == 200
    names = [d["name"] for d in r2.json()]
    assert "safety-v1" in names


@pytest.mark.django_db
def test_policy_draft_patch_and_delete():
    c = Client()
    r = c.post(
        "/api/v1/policies/",
        data={"name": "temp-policy", "content": {"version": 1}},
        content_type="application/json",
    )
    draft_id = r.json()["id"]

    r2 = c.patch(
        f"/api/v1/policies/{draft_id}/",
        data={"name": "temp-policy", "content": {"version": 2}},
        content_type="application/json",
    )
    assert r2.status_code == 200
    assert r2.json()["content"]["version"] == 2

    r3 = c.delete(f"/api/v1/policies/{draft_id}/")
    assert r3.status_code == 204

    r4 = c.get(f"/api/v1/policies/{draft_id}/")
    assert r4.status_code == 404


# ---------------------------------------------------------------------------
# Task list endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_task_list_returns_results():
    c = Client()
    c.post(
        "/api/v1/tasks/",
        data={"input_text": "list test task", "metadata": {}},
        content_type="application/json",
    )
    r = c.get("/api/v1/tasks/")
    assert r.status_code == 200
    body = r.json()
    assert "count" in body
    assert "results" in body
    assert body["count"] >= 1


@pytest.mark.django_db
def test_task_list_status_filter():
    c = Client()
    c.post(
        "/api/v1/tasks/",
        data={"input_text": "filter test task", "metadata": {}},
        content_type="application/json",
    )
    r = c.get("/api/v1/tasks/?status=completed")
    assert r.status_code == 200
    results = r.json()["results"]
    assert all(t["status"] == "completed" for t in results)


# ---------------------------------------------------------------------------
# Contract: Location header and enveloped 404 format
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sync_create_returns_location_header():
    """POST /api/v1/tasks/ (sync) must include a Location header pointing at the task."""
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Verify location header.", "metadata": {}},
        content_type="application/json",
    )
    assert r.status_code == 201
    task_id = r.json()["id"]
    assert "Location" in r
    assert r["Location"].endswith(f"/api/v1/tasks/{task_id}/")


@pytest.mark.django_db
def test_task_not_found_returns_enveloped_404():
    """All task 404s must use the standard envelope: {status, code, body}."""
    import uuid

    missing = uuid.uuid4()
    c = Client()
    r = c.get(f"/api/v1/tasks/{missing}/")
    assert r.status_code == 404
    body = r.json()
    assert body.get("status") == 404
    assert body.get("code") == "not_found"
    assert "detail" in (body.get("body") or {})


# ---------------------------------------------------------------------------
# Constitutional governance tests
# ---------------------------------------------------------------------------


def _pending_gate_service():
    """Return an OrchestrationService that requires human approval for every task."""
    from clawagora.governance.risk import RiskTier
    from clawagora.governance.gates import PendingHumanApprovalGate

    return OrchestrationService(gate=PendingHumanApprovalGate(review_at=RiskTier.LOW))


@pytest.mark.django_db
def test_pending_approval_gate_pauses_task():
    """A PendingHumanApprovalGate creates an ApprovalRequest and sets PENDING_APPROVAL."""
    set_orchestration_service(_pending_gate_service())
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Summarize the governance whitepaper.", "metadata": {}},
        content_type="application/json",
    )
    # Should succeed but task is paused, not completed
    assert r.status_code in (200, 201, 202)
    payload = r.json()
    assert payload["status"] == "pending_approval", payload
    ar = payload.get("approval_request")
    assert ar is not None
    assert ar["status"] == "pending"
    assert ar["risk_tier"] != ""
    # DB record exists
    task_id = payload["id"]
    assert ApprovalRequest.objects.filter(task_id=task_id).exists()


@pytest.mark.django_db
def test_approve_resumes_execution():
    """Approving a PENDING_APPROVAL task resumes execution to completion."""
    set_orchestration_service(_pending_gate_service())
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Refactor the authentication service.", "metadata": {}},
        content_type="application/json",
    )
    payload = r.json()
    assert payload["status"] == "pending_approval", payload
    task_id = payload["id"]

    # Approve — service needs auto-approve gate for the resumed run; swap it
    from clawagora.governance.gates import AutoApprovalGate

    set_orchestration_service(OrchestrationService(gate=AutoApprovalGate()))

    r2 = c.post(
        f"/api/v1/tasks/{task_id}/approve/",
        data={"note": "Looks safe."},
        content_type="application/json",
    )
    assert r2.status_code == 200, r2.json()
    body = r2.json()
    assert body["status"] == "completed", body
    ar = body.get("approval_request")
    assert ar["status"] == "approved"
    # decision_note carries the quorum summary; user note is in the vote rationale
    assert "approved" in ar["decision_note"]
    assert ar["votes"][0]["rationale"] == "Looks safe."


@pytest.mark.django_db
@override_settings(DEBUG=True, CLAWAGORA_EXPOSE_ERROR_DETAIL=True)
def test_reject_marks_task_needs_revision():
    """Judicial reject (封驳) sets needs_revision with approval_rejected (remediation path)."""
    set_orchestration_service(_pending_gate_service())
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Drop the production database.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]
    assert r.json()["status"] == "pending_approval"

    r2 = c.post(
        f"/api/v1/tasks/{task_id}/reject/",
        data={"note": "Too risky."},
        content_type="application/json",
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "needs_revision"
    assert body["error_code"] == "approval_rejected"
    assert body.get("error_detail", {}).get("branch") == "judicial"
    ar = body["approval_request"]
    assert ar["status"] == "rejected"
    # decision_note carries the quorum summary; user note is in the vote rationale
    assert "rejected" in ar["decision_note"]
    assert ar["votes"][0]["rationale"] == "Too risky."


@pytest.mark.django_db
def test_inject_guidance_on_pending_approval_task():
    """Guidance can be injected into a PENDING_APPROVAL task; it appears in metadata."""
    set_orchestration_service(_pending_gate_service())
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Migrate database schema.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]
    assert r.json()["status"] == "pending_approval"

    r2 = c.post(
        f"/api/v1/tasks/{task_id}/inject/",
        data={"guidance": "Use dry-run mode first."},
        content_type="application/json",
    )
    assert r2.status_code == 200, r2.json()
    body = r2.json()
    notes = body["metadata"].get("guidance_notes", [])
    assert len(notes) >= 1
    assert notes[0]["note"] == "Use dry-run mode first."


@pytest.mark.django_db
def test_retry_clears_approval_request():
    """retry_task deletes the previous ApprovalRequest so a fresh approval cycle starts."""
    set_orchestration_service(_pending_gate_service())
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Flush the cache cluster.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]
    assert r.json()["status"] == "pending_approval"

    # Force-reject via DB to put the task in FAILED state
    c.post(
        f"/api/v1/tasks/{task_id}/reject/",
        data={"note": "Denied."},
        content_type="application/json",
    )
    # Old ApprovalRequest still in DB, now status=rejected
    assert ApprovalRequest.objects.filter(task_id=task_id).exists()

    # Retry — a new pending cycle should create a fresh ApprovalRequest
    r3 = c.post(f"/api/v1/tasks/{task_id}/retry/", content_type="application/json")
    assert r3.status_code == 200, r3.json()
    body = r3.json()
    # After retry with PendingHumanApprovalGate still active, should be pending_approval again
    assert body["status"] == "pending_approval", body
    ar_qs = ApprovalRequest.objects.filter(task_id=task_id)
    assert ar_qs.count() == 1
    assert ar_qs.first().status == "pending"


@pytest.mark.django_db
def test_active_policy_enforces_executor_allowlist():
    """An active PolicyDraft with a restrictive allowlist blocks disallowed executors."""
    # Create and activate a policy that allows only 'research_executor'
    c = Client()
    r = c.post(
        "/api/v1/policies/",
        data={
            "name": "Strict Policy",
            "content": {"allowed_executors": ["research_executor"]},
        },
        content_type="application/json",
    )
    assert r.status_code == 201
    draft_id = r.json()["id"]

    r2 = c.post(f"/api/v1/policies/{draft_id}/activate/", content_type="application/json")
    assert r2.status_code == 200
    assert r2.json()["is_active"] is True

    # Submit a CODING task — it should fail validation (coding_executor not allowed)
    r3 = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Refactor the payment service entirely.", "metadata": {}},
        content_type="application/json",
    )
    body = r3.json()
    assert body["status"] == "failed", body
    assert body["error_code"] in (
        "policy_violation",
        "pipeline_execution_failed",
        "validation_failed",
    ), body


@pytest.mark.django_db
def test_policy_activate_deactivates_others():
    """Activating one PolicyDraft deactivates all others atomically."""
    c = Client()
    ids = []
    for i in range(3):
        r = c.post(
            "/api/v1/policies/",
            data={"name": f"Policy {i}", "content": {}},
            content_type="application/json",
        )
        ids.append(r.json()["id"])

    # Activate the second one
    act_id = ids[1]
    r2 = c.post(f"/api/v1/policies/{act_id}/activate/", content_type="application/json")
    assert r2.status_code == 200
    assert r2.json()["is_active"] is True

    # The other two must be inactive
    for pid in ids:
        draft = PolicyDraft.objects.get(id=pid)
        expected = pid == act_id
        assert draft.is_active == expected, f"Policy {pid} expected is_active={expected}"


@pytest.mark.django_db
def test_deactivate_all_policies():
    """POST /policies/deactivate/ deactivates every draft."""
    c = Client()
    r = c.post(
        "/api/v1/policies/",
        data={"name": "Active Policy", "content": {}},
        content_type="application/json",
    )
    draft_id = r.json()["id"]
    c.post(f"/api/v1/policies/{draft_id}/activate/", content_type="application/json")
    assert PolicyDraft.objects.filter(is_active=True).exists()

    r2 = c.post("/api/v1/policies/deactivate/", content_type="application/json")
    assert r2.status_code == 200
    assert not PolicyDraft.objects.filter(is_active=True).exists()


# ---------------------------------------------------------------------------
# Quorum voting tests (ekklesia — multi-reviewer approval panel)
# ---------------------------------------------------------------------------


def _quorum_gate_service(quorum: int):
    """Return a service where every task needs quorum N votes to resolve."""
    from clawagora.governance.gates import PendingHumanApprovalGate
    from clawagora.governance.risk import RiskTier

    return OrchestrationService(
        gate=PendingHumanApprovalGate(review_at=RiskTier.LOW, quorum=quorum)
    )


@pytest.mark.django_db
def test_quorum_1_single_vote_resolves():
    """quorum=1: a single approve vote via /vote/ resolves the request immediately."""
    from clawagora.governance.gates import AutoApprovalGate

    set_orchestration_service(_quorum_gate_service(1))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Deploy the hotfix to staging.", "metadata": {}},
        content_type="application/json",
    )
    assert r.json()["status"] == "pending_approval"
    task_id = r.json()["id"]
    ar = r.json()["approval_request"]
    assert ar["quorum"] == 1
    assert ar["threshold"] == 1

    # Swap to auto gate so the resumed run passes
    set_orchestration_service(OrchestrationService(gate=AutoApprovalGate()))

    rv = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "approve", "rationale": "LGTM"},
        content_type="application/json",
    )
    assert rv.status_code == 200, rv.json()
    body = rv.json()
    assert body["status"] == "completed"
    ar2 = body["approval_request"]
    assert ar2["status"] == "approved"
    assert ar2["approve_count"] == 1
    votes = ar2["votes"]
    assert len(votes) == 1
    assert votes[0]["voter_id"] == "alice"
    assert votes[0]["rationale"] == "LGTM"


@pytest.mark.django_db
def test_quorum_3_requires_two_approve_votes():
    """quorum=3: two approve votes are needed (threshold=2); first vote returns 202."""
    from clawagora.governance.gates import AutoApprovalGate

    set_orchestration_service(_quorum_gate_service(3))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Rotate the production encryption keys.", "metadata": {}},
        content_type="application/json",
    )
    assert r.json()["status"] == "pending_approval"
    task_id = r.json()["id"]
    ar = r.json()["approval_request"]
    assert ar["quorum"] == 3
    assert ar["threshold"] == 2

    # First approve vote — not yet resolved
    rv1 = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "approve", "rationale": "Looks good to me."},
        content_type="application/json",
    )
    assert rv1.status_code == 202, rv1.json()
    body1 = rv1.json()
    assert body1["status"] == "pending_approval"
    assert body1["approval_request"]["approve_count"] == 1
    assert body1["approval_request"]["reject_count"] == 0

    # Second approve vote — reaches threshold (2/3), resolves
    set_orchestration_service(OrchestrationService(gate=AutoApprovalGate()))
    rv2 = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "bob", "decision": "approve", "rationale": "All clear."},
        content_type="application/json",
    )
    assert rv2.status_code == 200, rv2.json()
    body2 = rv2.json()
    assert body2["status"] == "completed"
    ar2 = body2["approval_request"]
    assert ar2["status"] == "approved"
    assert ar2["approve_count"] == 2


@pytest.mark.django_db
def test_quorum_3_majority_reject_resolves():
    """quorum=3, two reject votes (threshold=2) reject the task."""
    set_orchestration_service(_quorum_gate_service(3))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Reformat the entire codebase.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]
    assert r.json()["status"] == "pending_approval"

    # First reject
    rv1 = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "reject", "rationale": "Too risky."},
        content_type="application/json",
    )
    assert rv1.status_code == 202
    assert rv1.json()["status"] == "pending_approval"

    # Second reject — reaches threshold
    rv2 = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "bob", "decision": "reject", "rationale": "Not now."},
        content_type="application/json",
    )
    assert rv2.status_code == 200
    body2 = rv2.json()
    assert body2["status"] == "needs_revision"
    assert body2["error_code"] == "approval_rejected"
    assert body2["approval_request"]["status"] == "rejected"
    assert body2["approval_request"]["reject_count"] == 2


@pytest.mark.django_db
def test_duplicate_vote_returns_409():
    """A voter may only vote once per request; a second vote returns 409."""
    set_orchestration_service(_quorum_gate_service(3))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Archive old audit logs.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]

    c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "approve"},
        content_type="application/json",
    )
    dup = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "reject"},
        content_type="application/json",
    )
    assert dup.status_code == 409


@pytest.mark.django_db
def test_vote_invalid_decision_returns_400():
    """A vote with an unknown decision string is rejected with 400."""
    set_orchestration_service(_quorum_gate_service(3))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Rebuild the search index.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]

    rv = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "maybe"},
        content_type="application/json",
    )
    assert rv.status_code == 400


@pytest.mark.django_db
def test_votes_list_endpoint():
    """GET /tasks/<id>/votes/ returns all cast votes."""
    set_orchestration_service(_quorum_gate_service(3))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Compress backup archives.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]

    c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "approve", "rationale": "Fine."},
        content_type="application/json",
    )
    c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "bob", "decision": "reject", "rationale": "Wait."},
        content_type="application/json",
    )

    rv = c.get(f"/api/v1/tasks/{task_id}/votes/")
    assert rv.status_code == 200
    votes = rv.json()
    assert len(votes) == 2
    voter_ids = {v["voter_id"] for v in votes}
    assert voter_ids == {"alice", "bob"}
    decisions = {v["voter_id"]: v["decision"] for v in votes}
    assert decisions["alice"] == "approve"
    assert decisions["bob"] == "reject"


@pytest.mark.django_db
def test_approval_request_serializer_includes_vote_counts():
    """The approval_request embedded in task response shows quorum/threshold/counts/votes."""
    set_orchestration_service(_quorum_gate_service(5))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Run the capacity test.", "metadata": {}},
        content_type="application/json",
    )
    assert r.json()["status"] == "pending_approval"
    task_id = r.json()["id"]

    # Cast two votes
    for voter_id in ("alice", "bob"):
        c.post(
            f"/api/v1/tasks/{task_id}/vote/",
            data={"voter_id": voter_id, "decision": "approve"},
            content_type="application/json",
        )

    detail = c.get(f"/api/v1/tasks/{task_id}/").json()
    ar = detail["approval_request"]
    assert ar["quorum"] == 5
    assert ar["threshold"] == 3
    assert ar["approve_count"] == 2
    assert ar["reject_count"] == 0
    assert len(ar["votes"]) == 2


@pytest.mark.django_db
def test_gate_quorum_exposed_on_approval_request():
    """quorum field set on ApprovalRequest matches the gate's quorum parameter."""
    from orchestration.models import ApprovalRequest

    set_orchestration_service(_quorum_gate_service(7))
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Perform rolling restart of all nodes.", "metadata": {}},
        content_type="application/json",
    )
    task_id = r.json()["id"]
    ar_db = ApprovalRequest.objects.get(task_id=task_id)
    assert ar_db.quorum == 7
    assert ar_db.quorum // 2 + 1 == 4  # majority threshold


# ---------------------------------------------------------------------------
# 三权分立 — Separation-of-Powers governance tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_voter_allowlist_blocks_unauthorized_voter():
    """司法权：when ALLOWED_VOTERS is set, unlisted voter_id is rejected with 403."""
    from django.test import override_settings

    set_orchestration_service(_pending_gate_service())
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Flush the redis cache cluster.", "metadata": {}},
        content_type="application/json",
    )
    assert r.json()["status"] == "pending_approval"
    task_id = r.json()["id"]

    with override_settings(CLAWAGORA_APPROVAL_ALLOWED_VOTERS=["alice", "bob"]):
        rv = c.post(
            f"/api/v1/tasks/{task_id}/vote/",
            data={"voter_id": "mallory", "decision": "approve"},
            content_type="application/json",
        )
    assert rv.status_code == 403


@pytest.mark.django_db
def test_self_approval_blocked():
    """提案人自批禁止：task submitter cannot approve their own submission."""
    set_orchestration_service(_pending_gate_service())
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={"input_text": "Update DNS records to new datacenter.", "metadata": {}},
        content_type="application/json",
        HTTP_X_SUBMITTED_BY="alice",
    )
    assert r.json()["status"] == "pending_approval"
    assert r.json()["submitted_by"] == "alice"
    task_id = r.json()["id"]

    rv = c.post(
        f"/api/v1/tasks/{task_id}/vote/",
        data={"voter_id": "alice", "decision": "approve", "rationale": "I approve my own work."},
        content_type="application/json",
    )
    assert rv.status_code == 403


@pytest.mark.django_db
def test_policy_write_requires_policy_key():
    """立法权：policy mutations require X-Policy-Key when CLAWAGORA_POLICY_KEY is configured."""
    from django.test import override_settings

    c = Client()
    with override_settings(CLAWAGORA_POLICY_KEY="secret-policy-key", CLAWAGORA_API_KEY="task-key"):
        # No key provided → 403
        r_no_key = c.post(
            "/api/v1/policies/",
            data={"name": "test-policy", "content": {}},
            content_type="application/json",
        )
        # Wrong key → 403
        r_wrong_key = c.post(
            "/api/v1/policies/",
            data={"name": "test-policy", "content": {}},
            content_type="application/json",
            HTTP_X_POLICY_KEY="wrong-key",
        )
        # Correct policy key → accepted (not 403)
        r_good_key = c.post(
            "/api/v1/policies/",
            data={"name": "test-policy", "content": {}},
            content_type="application/json",
            HTTP_X_POLICY_KEY="secret-policy-key",
        )
    assert r_no_key.status_code == 403
    assert r_wrong_key.status_code == 403
    assert r_good_key.status_code != 403

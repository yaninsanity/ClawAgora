"""OpenClaw delegate + callback integration (mocked HTTP)."""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.db import connection
from django.test import Client, override_settings

from orchestration.openclaw_delegate import build_delegate_payload, sign_body
from orchestration.models import Task


def _callback_headers(secret: str, raw: bytes, *, nonce: str | None = None, ts: int | None = None) -> dict[str, str]:
    sig = sign_body(secret, raw)
    return {
        "HTTP_X_CLAWAGORA_SIGNATURE": sig,
        "HTTP_X_CLAWAGORA_TIMESTAMP": str(int(time.time()) if ts is None else ts),
        "HTTP_X_CLAWAGORA_NONCE": nonce or uuid.uuid4().hex,
    }


def _create_delegated_task(c: Client) -> str:
    with patch("orchestration.openclaw_delegate.post_delegate", return_value=(True, 200, "ok")):
        created = c.post(
            "/api/v1/tasks/",
            data={
                "input_text": "Plan migration.",
                "metadata": {"openclaw": {"delegate": True}},
            },
            content_type="application/json",
        )
    assert created.status_code == 201
    return created.json()["id"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://bridge.test/delegate",
    CLAWAGORA_PUBLIC_BASE_URL="http://api.example",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
    CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON='{"default_agents":["a","b"],"by_risk":{"high":["h1"]}}',
)
def test_build_delegate_payload_includes_context_from_metadata():
    md = {
        "openclaw": {"delegate": True},
        "clawagora_context": {"session_id": "sess-1", "memory_refs": ["m1"]},
    }
    p = build_delegate_payload(
        task_id="00000000-0000-0000-0000-000000000001",
        input_text="hi",
        metadata=md,
        risk_tier="low",
        agents=["a1"],
        callback_url="http://x/cb",
    )
    assert p["metadata"] == md
    assert p["context"] == {"session_id": "sess-1", "memory_refs": ["m1"]}
    assert p["callback_schema"] == "clawagora.openclaw.callback.v1"


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://bridge.test/delegate",
    CLAWAGORA_PUBLIC_BASE_URL="http://api.example",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="x",
    CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON='{"default_agents":["a","b"],"by_risk":{"high":["h1"]}}',
)
def test_openclaw_status_includes_delegate_snapshot():
    c = Client()
    r = c.get("/api/v1/integrations/openclaw/status/")
    assert r.status_code == 200
    body = r.json()
    assert "delegate" in body
    deleg = body["delegate"]
    assert deleg["enabled"] is True
    assert deleg["url_configured"] is True
    assert deleg["delegate_url"] == "http://bridge.test/delegate"
    assert deleg["callback_url"] == "http://api.example/api/v1/integrations/openclaw/callback/"
    assert deleg["webhook_secret_configured"] is True
    assert deleg["callback_guard_cache_backend"] in ("locmem", "redis")
    assert "knowledge" in deleg
    assert "capability_require_sha256" in deleg["knowledge"]
    assert deleg["agent_config"]["default_agents"] == ["a", "b"]
    assert "high" in deleg["agent_config"]["by_risk_tiers"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_PUBLIC_BASE_URL="http://clawagora.test",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
    CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON='{"default_agents":["bingbu","libu"]}',
)
def test_create_with_delegate_metadata_runs_openclaw_path_and_callback_completes():
    c = Client()
    with patch(
        "orchestration.openclaw_delegate.post_delegate",
        return_value=(True, 200, "ok"),
    ):
        r = c.post(
            "/api/v1/tasks/",
            data={
                "input_text": "Plan migration.",
                "metadata": {"openclaw": {"delegate": True}},
            },
            content_type="application/json",
        )
    assert r.status_code == 201, r.content
    body = r.json()
    task_id = body["id"]
    assert body["status"] == "running"
    assert body["metadata"]["openclaw"]["phase"] == "awaiting_callback"

    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "done", "artifacts": []},
        "agents": ["bingbu"],
    }
    raw = json.dumps(payload).encode("utf-8")
    r3 = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **_callback_headers("testsecret", raw),
    )
    assert r3.status_code == 200, r3.content
    done = r3.json()
    assert done["status"] == "completed"
    assert done["receipt"]["body"]["source"] == "openclaw"
    assert done["receipt"]["body"].get("openclaw_artifacts") == []


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_PUBLIC_BASE_URL="http://clawagora.test",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
    CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON='{"default_agents":["a1"]}',
)
def test_openclaw_callback_persists_artifacts_and_receipt():
    c = Client()
    with patch(
        "orchestration.openclaw_delegate.post_delegate",
        return_value=(True, 200, "ok"),
    ):
        r = c.post(
            "/api/v1/tasks/",
            data={
                "input_text": "Design API.",
                "metadata": {"openclaw": {"delegate": True}},
            },
            content_type="application/json",
        )
    assert r.status_code == 201
    task_id = r.json()["id"]
    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "final"},
        "artifacts": [
            {"role": "proposal", "agent_id": "p1", "content": "Plan A"},
            {"role": "critique", "text": "Add tests", "meta": {"severity": "low"}},
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    r3 = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **_callback_headers("testsecret", raw),
    )
    assert r3.status_code == 200, r3.content
    done = r3.json()
    arts = done["metadata"]["openclaw"]["artifacts"]
    assert len(arts) == 2
    assert arts[0]["role"] == "proposal"
    assert arts[0]["content"] == "Plan A"
    assert arts[1]["role"] == "critique"
    assert arts[1]["content"] == "Add tests"
    assert arts[1]["meta"] == {"severity": "low"}
    rb = done["receipt"]["body"]
    assert rb["openclaw_artifacts"] == arts


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_PUBLIC_BASE_URL="http://clawagora.test",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
    CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON='{"default_agents":["a1"]}',
)
def test_openclaw_callback_rejects_non_list_artifacts():
    c = Client()
    with patch(
        "orchestration.openclaw_delegate.post_delegate",
        return_value=(True, 200, "ok"),
    ):
        r = c.post(
            "/api/v1/tasks/",
            data={
                "input_text": "x",
                "metadata": {"openclaw": {"delegate": True}},
            },
            content_type="application/json",
        )
    task_id = r.json()["id"]
    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "x"},
        "artifacts": "not-a-list",
    }
    raw = json.dumps(payload).encode("utf-8")
    r3 = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **_callback_headers("testsecret", raw),
    )
    assert r3.status_code == 409


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="",
)
def test_delegate_fails_without_delegate_url():
    c = Client()
    r = c.post(
        "/api/v1/tasks/",
        data={
            "input_text": "x",
            "metadata": {"openclaw": {"delegate": True}},
        },
        content_type="application/json",
    )
    assert r.status_code == 201
    assert r.json()["status"] == "failed"
    assert r.json()["error_code"] == "openclaw_delegate_failed"


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
)
def test_callback_rejects_invalid_signature():
    c = Client()
    task_id = _create_delegated_task(c)
    payload = {"task_id": task_id, "status": "failed", "error": "x"}
    raw = json.dumps(payload).encode("utf-8")
    r = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        HTTP_X_CLAWAGORA_SIGNATURE="bad-signature",
        HTTP_X_CLAWAGORA_TIMESTAMP=str(int(time.time())),
        HTTP_X_CLAWAGORA_NONCE=uuid.uuid4().hex,
    )
    assert r.status_code == 403
    assert "signature" in r.json()["detail"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
)
def test_manual_delegate_rejects_invalid_agents_payload():
    c = Client()
    task = Task.objects.create(input_text="hello", metadata={}, status=Task.Status.RECEIVED)
    task_id = str(task.id)
    r = c.post(
        f"/api/v1/tasks/{task_id}/integrations/openclaw/delegate/",
        data={"agents": {"not": "a list"}},
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "agents must be an array" in r.json()["detail"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
)
def test_callback_guard_rejects_replay_nonce():
    c = Client()
    task_id = _create_delegated_task(c)
    payload = {"task_id": task_id, "status": "failed", "error": "bridge fail", "external_id": "x-1"}
    raw = json.dumps(payload).encode("utf-8")
    nonce = uuid.uuid4().hex
    headers = _callback_headers("testsecret", raw, nonce=nonce)
    first = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **headers,
    )
    assert first.status_code == 200
    second = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **headers,
    )
    assert second.status_code == 403
    assert "replay_detected" in second.json()["detail"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
)
def test_callback_idempotent_on_external_id_after_terminal():
    c = Client()
    task_id = _create_delegated_task(c)
    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "done", "artifacts": []},
        "agents": ["bingbu"],
        "external_id": "bridge-42",
    }
    raw = json.dumps(payload).encode("utf-8")
    r1 = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **_callback_headers("testsecret", raw, nonce=uuid.uuid4().hex),
    )
    assert r1.status_code == 200
    r2 = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **_callback_headers("testsecret", raw, nonce=uuid.uuid4().hex),
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
)
def test_callback_guard_rejects_same_nonce_with_different_body():
    c = Client()
    task_id = _create_delegated_task(c)
    nonce = uuid.uuid4().hex
    p1 = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "done", "artifacts": []},
        "external_id": "bridge-guard-nonce-1",
    }
    raw1 = json.dumps(p1).encode("utf-8")
    r1 = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw1,
        content_type="application/json",
        **_callback_headers("testsecret", raw1, nonce=nonce),
    )
    assert r1.status_code == 200

    p2 = {
        "task_id": task_id,
        "status": "failed",
        "error_code": "unexpected",
        "error": "tampered retry",
        "external_id": "bridge-guard-nonce-2",
    }
    raw2 = json.dumps(p2).encode("utf-8")
    r2 = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw2,
        content_type="application/json",
        **_callback_headers("testsecret", raw2, nonce=nonce),
    )
    assert r2.status_code == 403
    assert "replay_detected" in r2.json()["detail"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
)
def test_callback_guard_requires_timestamp_and_nonce_by_default():
    c = Client()
    task_id = _create_delegated_task(c)
    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "done", "artifacts": []},
        "external_id": "bridge-guard-default",
    }
    raw = json.dumps(payload).encode("utf-8")
    r = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        HTTP_X_CLAWAGORA_SIGNATURE=sign_body("testsecret", raw),
    )
    assert r.status_code == 403
    assert "missing_timestamp_or_nonce" in r.json()["detail"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
    CLAWAGORA_OPENCLAW_CALLBACK_MAX_SKEW_SEC=5,
)
def test_callback_guard_rejects_stale_timestamp():
    c = Client()
    task_id = _create_delegated_task(c)
    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "done", "artifacts": []},
        "external_id": "bridge-stale-ts",
    }
    raw = json.dumps(payload).encode("utf-8")
    old_ts = int(time.time()) - 60
    r = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        **_callback_headers("testsecret", raw, ts=old_ts),
    )
    assert r.status_code == 403
    assert "timestamp_out_of_window" in r.json()["detail"]


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
    CLAWAGORA_OPENCLAW_CALLBACK_REQUIRE_GUARD=False,
)
def test_callback_guard_can_be_disabled_for_compatibility():
    c = Client()
    task_id = _create_delegated_task(c)
    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "done", "artifacts": []},
        "external_id": "bridge-guard-disabled",
    }
    raw = json.dumps(payload).encode("utf-8")
    r = c.post(
        "/api/v1/integrations/openclaw/callback/",
        data=raw,
        content_type="application/json",
        HTTP_X_CLAWAGORA_SIGNATURE=sign_body("testsecret", raw),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


@pytest.mark.django_db(transaction=True)
@override_settings(
    CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=True,
    CLAWAGORA_OPENCLAW_DELEGATE_URL="http://openclaw.test/delegate",
    CLAWAGORA_OPENCLAW_WEBHOOK_SECRET="testsecret",
)
def test_concurrent_callbacks_same_task_are_safe_with_same_external_id():
    if connection.vendor == "sqlite":
        pytest.skip("Concurrent callback write race test requires non-SQLite backend.")
    task_id = _create_delegated_task(Client())
    payload = {
        "task_id": task_id,
        "status": "completed",
        "synthesis": {"summary": "done", "artifacts": []},
        "agents": ["planner", "reviewer"],
        "external_id": "bridge-race-1",
    }
    raw = json.dumps(payload).encode("utf-8")

    def _post_once(nonce: str) -> int:
        c = Client()
        r = c.post(
            "/api/v1/integrations/openclaw/callback/",
            data=raw,
            content_type="application/json",
            **_callback_headers("testsecret", raw, nonce=nonce),
        )
        return r.status_code

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_post_once, uuid.uuid4().hex) for _ in range(2)]
    codes = sorted([f.result() for f in futures])
    assert codes == [200, 200]

    latest = Client().get(f"/api/v1/tasks/{task_id}/")
    assert latest.status_code == 200
    body = latest.json()
    assert body["status"] == "completed"
    assert body["metadata"]["openclaw"]["phase"] == "callback_received"
    assert body["metadata"]["openclaw"]["external_id"] == "bridge-race-1"

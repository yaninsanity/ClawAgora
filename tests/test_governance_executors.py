"""Governance executors discovery — legislative allowlist aligns with TaskPipeline registry."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_governance_executors_lists_pipeline_ids():
    c = Client()
    r = c.get("/api/v1/governance/executors/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("schema") == "clawagora.governance.executors.v1"
    ex = body["executors"]
    assert isinstance(ex, list)
    ids = {e["id"] for e in ex}
    assert "executor_echo" in ids
    assert "executor_transform" in ids
    assert all("label" in e for e in ex)

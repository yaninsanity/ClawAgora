"""Governance summary aggregate endpoint."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_governance_summary_schema_and_sections():
    c = Client()
    r = c.get("/api/v1/governance/summary/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("schema") == "clawagora.governance.summary.v1"
    assert "version" in body
    assert "policy" in body
    assert "capabilities" in body
    assert "prompts" in body
    assert "integrations" in body
    assert "draft_count" in body["policy"]
    assert "circuit_breaker" in body["prompts"]
    assert "registry_keys" in body["prompts"]
    assert "openclaw_delegate" in body["integrations"]

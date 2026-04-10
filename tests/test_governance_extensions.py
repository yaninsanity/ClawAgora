"""Governance extensions: approval templates, audit anchor, org/subjects, policy proposals."""

import json

import pytest
from django.test import Client


@pytest.mark.django_db
def test_approval_templates_lists_runtime_and_seeded_templates():
    c = Client()
    r = c.get("/api/v1/governance/approval-templates/")
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "clawagora.governance.approval_templates.v1"
    assert "runtime" in body
    assert body["runtime"]["approval_quorum"] >= 1
    slugs = {t["slug"] for t in body["templates"]}
    assert "four_eyes" in slugs
    assert "single_operator" in slugs
    assert body.get("org_recommendation") is None


@pytest.mark.django_db
def test_approval_templates_org_recommendation_from_linked_unit():
    from orchestration.models import ApprovalPolicyTemplate, OrganizationUnit

    tpl = ApprovalPolicyTemplate.objects.get(slug="four_eyes")
    OrganizationUnit.objects.create(slug="fin", name="Finance", approval_template=tpl)
    c = Client()
    r = c.get("/api/v1/governance/approval-templates/?org_slug=fin")
    assert r.status_code == 200
    rec = r.json()["org_recommendation"]
    assert rec["recommended_quorum"] == 2
    assert rec["template_slug"] == "four_eyes"
    assert any("CLAWAGORA_APPROVAL_QUORUM=2" in x for x in rec["env_exports"])


@pytest.mark.django_db
def test_audit_anchor_returns_root_hash():
    c = Client()
    r = c.get("/api/v1/governance/audit-anchor/")
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "clawagora.governance.audit_anchor.v1"
    assert len(body["root_hash"]) == 64
    assert "chain_tail" in body


@pytest.mark.django_db
def test_policy_rejects_unknown_content_keys():
    c = Client()
    r = c.post(
        "/api/v1/policies/",
        data=json.dumps({"name": "bad", "content": {"natural_language_rule": "be nice"}}),
        content_type="application/json",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_policy_evolution_proposal_accept_creates_inactive_draft():
    c = Client()
    r1 = c.post(
        "/api/v1/policies/proposals/",
        data=json.dumps(
            {
                "proposed_content": {"deny_patterns": ["foo"]},
                "source": "manual",
                "rationale": "test",
            }
        ),
        content_type="application/json",
    )
    assert r1.status_code == 201, r1.content
    pid = r1.json()["id"]
    r2 = c.patch(
        f"/api/v1/policies/proposals/{pid}/",
        data=json.dumps({"action": "accept", "draft_name": "from-proposal", "note": "ok"}),
        content_type="application/json",
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "accepted"
    assert r2.json()["derived_policy_draft_id"]


@pytest.mark.django_db
def test_task_external_subject_from_header_when_configured():
    from django.test import override_settings

    c = Client()
    with override_settings(CLAWAGORA_IDENTITY_EXTERNAL_SUBJECT_HEADER="X-Test-Sub"):
        r = c.post(
            "/api/v1/tasks/",
            data=json.dumps({"input_text": "x", "metadata": {}}),
            content_type="application/json",
            HTTP_X_TEST_SUB="oidc|alice",
        )
    assert r.status_code in (200, 201)
    assert r.json()["metadata"].get("external_subject") == "oidc|alice"

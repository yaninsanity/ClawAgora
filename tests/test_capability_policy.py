"""Capability bundle integrity rules (knowledge governance)."""

import uuid

import pytest
from django.core.management import call_command
from django.test import Client, override_settings

from orchestration.models import CapabilityBundle


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_CAPABILITY_REQUIRE_SHA256=True,
    CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL=True,
)
def test_active_capability_requires_url_and_sha256():
    c = Client()
    slug = f"skill-a-{uuid.uuid4().hex[:8]}"
    r = c.post(
        "/api/v1/capabilities/",
        data={
            "name": "Skill A",
            "slug": slug,
            "is_active": True,
        },
        content_type="application/json",
    )
    assert r.status_code == 400
    body = r.json()
    inner = body.get("body") or body
    assert "source_url" in inner or "source_sha256" in inner


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_CAPABILITY_REQUIRE_SHA256=True,
    CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL=True,
)
def test_active_capability_succeeds_with_pins():
    c = Client()
    slug = f"skill-b-{uuid.uuid4().hex[:8]}"
    r = c.post(
        "/api/v1/capabilities/",
        data={
            "name": "Skill B",
            "slug": slug,
            "source_url": "https://example.com/skill.md",
            "source_sha256": "a" * 64,
            "is_active": True,
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_CAPABILITY_REQUIRE_SHA256=True,
)
def test_inactive_capability_may_omit_sha256():
    c = Client()
    slug = f"skill-c-{uuid.uuid4().hex[:8]}"
    r = c.post(
        "/api/v1/capabilities/",
        data={
            "name": "Skill C",
            "slug": slug,
            "is_active": False,
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_CAPABILITY_REQUIRE_SHA256=True,
)
def test_patch_activate_validates_before_save():
    bundle = CapabilityBundle.objects.create(
        name="Draft",
        slug=f"skill-d-{uuid.uuid4().hex[:8]}",
        source_url="",
        source_sha256="",
        is_active=False,
    )
    c = Client()
    r = c.patch(
        f"/api/v1/capabilities/{bundle.id}/",
        data={"is_active": True},
        content_type="application/json",
    )
    assert r.status_code == 400
    bundle.refresh_from_db()
    assert bundle.is_active is False


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_CAPABILITY_REQUIRE_SHA256=True,
)
def test_capability_integrity_command_lists_offenders(capsys):
    CapabilityBundle.objects.create(
        name="Loose",
        slug=f"loose-{uuid.uuid4().hex[:8]}",
        is_active=True,
        source_sha256="",
    )
    call_command("clawagora_capability_integrity")
    captured = capsys.readouterr().out
    assert "offenders=" in captured

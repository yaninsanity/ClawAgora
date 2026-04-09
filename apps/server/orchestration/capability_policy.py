"""Governance rules for capability / knowledge bundle registration."""

from __future__ import annotations

from django.conf import settings
from rest_framework.exceptions import ValidationError


def validate_active_capability_bundle(*, source_url: str, source_sha256: str) -> None:
    """When a bundle is active, optionally require pinned source URL and SHA-256.

    Set CLAWAGORA_CAPABILITY_REQUIRE_SHA256=1 and/or CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL=1.
    """
    require_sha = bool(getattr(settings, "CLAWAGORA_CAPABILITY_REQUIRE_SHA256", False))
    require_url = bool(getattr(settings, "CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL", False))
    if not require_sha and not require_url:
        return
    url = (source_url or "").strip()
    sha = (source_sha256 or "").strip()
    if require_url and not url:
        raise ValidationError(
            {"source_url": "Active bundles require source_url when CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL=1."}
        )
    if require_sha and len(sha) != 64:
        raise ValidationError(
            {
                "source_sha256": "Active bundles require a 64-hex source_sha256 when CLAWAGORA_CAPABILITY_REQUIRE_SHA256=1."
            }
        )

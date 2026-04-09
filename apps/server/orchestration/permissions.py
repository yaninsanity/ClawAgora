from __future__ import annotations

import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class OptionalApiKeyPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        expected: str = settings.CLAWAGORA_API_KEY
        if not expected:
            return True
        provided = (request.headers.get("X-API-Key") or "").strip()
        return hmac.compare_digest(provided, expected)


class PolicyWritePermission(BasePermission):
    """Requires X-Policy-Key for policy mutation operations.

    This enforces legislative / executive separation: the principal
    authorised to write and activate policies (立法权) must be distinct
    from the principal that submits and approves tasks (行政/司法权).

    Reads CLAWAGORA_POLICY_KEY via app_settings.policy_write_key().
    Falls back to CLAWAGORA_API_KEY when CLAWAGORA_POLICY_KEY is unset,
    so single-key deployments are unaffected.
    Read-only methods (GET, HEAD, OPTIONS) are always permitted.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        from orchestration.app_settings import policy_write_key

        expected = policy_write_key()
        if not expected:
            return True
        provided = (request.headers.get("X-Policy-Key") or "").strip()
        return hmac.compare_digest(provided, expected)


class GovernanceWritePermission(BasePermission):
    """Requires X-Governance-Key for governance mutation operations."""

    def has_permission(self, request, view) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        from orchestration.app_settings import governance_write_key

        expected = governance_write_key()
        if not expected:
            return True
        provided = (request.headers.get("X-Governance-Key") or "").strip()
        return hmac.compare_digest(provided, expected)

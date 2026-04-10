"""Off-chain rolling hash over policy activation events — anchor ``root_hash`` externally (ledger, WORM)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings

from orchestration.models import PolicyActivationEvent


def build_audit_anchor_bundle(*, limit: int | None = None) -> dict[str, Any]:
    """Return a deterministic hash chain over recent ``PolicyActivationEvent`` rows (oldest first)."""
    max_n = settings.CLAWAGORA_AUDIT_ANCHOR_MAX_EVENTS
    n = min(limit or max_n, max_n)
    qs = PolicyActivationEvent.objects.order_by("created_at", "id")[:n]
    rows: list[dict[str, Any]] = []
    for e in qs:
        rows.append(
            {
                "t": "policy_activation",
                "id": str(e.id),
                "at": e.created_at.isoformat(),
                "action": e.action,
                "policy_draft_id": str(e.policy_draft_id) if e.policy_draft_id else None,
                "previous_active_id": str(e.previous_active_id) if e.previous_active_id else None,
            }
        )
    prev = ""
    chain: list[dict[str, Any]] = []
    for row in rows:
        canon = json.dumps(row, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(f"{prev}:{canon}".encode()).hexdigest()
        prev = digest
        chain.append({"record": row, "rolling_hash": digest})
    tail = chain[-32:] if len(chain) > 32 else chain
    if not rows:
        prev = hashlib.sha256(b"clawagora.governance.audit_anchor.empty:v1").hexdigest()
    return {
        "schema": "clawagora.governance.audit_anchor.v1",
        "note": (
            "Off-chain chain only. Publish root_hash to tamper-evident storage; "
            "on-chain consensus and cross-org trust are out of scope for this service."
        ),
        "root_hash": prev,
        "event_count": len(rows),
        "chain_tail": tail,
    }

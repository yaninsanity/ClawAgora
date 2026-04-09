from __future__ import annotations

import re
import uuid

from clawagora.contracts.task import IntakeEnvelope


class IntakeService:
    def accept(
        self,
        raw_text: str,
        metadata: dict | None = None,
        *,
        request_id: str | None = None,
    ) -> IntakeEnvelope:
        text = (raw_text or "").strip()
        normalized = self._normalize(text)
        rid = request_id if request_id is not None else str(uuid.uuid4())
        return IntakeEnvelope(
            request_id=rid,
            raw_text=raw_text,
            metadata=dict(metadata or {}),
            normalized_text=normalized,
        )

    def _normalize(self, text: str) -> str:
        collapsed = re.sub(r"\s+", " ", text).strip()
        return collapsed

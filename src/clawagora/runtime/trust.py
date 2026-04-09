from __future__ import annotations

from pydantic import BaseModel, Field


class TrustScore(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)

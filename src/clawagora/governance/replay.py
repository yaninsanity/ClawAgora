from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ReplayMode(StrEnum):
    EVENTS = "events"
    DECISIONS = "decisions"


class ReplayBundle(BaseModel):
    mode: ReplayMode
    task_id: str
    records: list[dict[str, Any]] = Field(default_factory=list)

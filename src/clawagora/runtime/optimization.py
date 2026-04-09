from __future__ import annotations

from pydantic import BaseModel, Field


class OptimizationRecommendation(BaseModel):
    code: str
    message: str
    severity: str = "info"


class OptimizationReport(BaseModel):
    task_id: str
    items: list[OptimizationRecommendation] = Field(default_factory=list)

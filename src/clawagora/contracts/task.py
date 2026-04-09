from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskState(StrEnum):
    RECEIVED = "received"
    CLASSIFIED = "classified"
    PLANNED = "planned"
    VALIDATING = "validating"
    VALIDATED = "validated"
    DISPATCHING = "dispatching"
    EXECUTING = "executing"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPhase(StrEnum):
    INTAKE = "intake"
    CLASSIFY = "classify"
    PLAN = "plan"
    VALIDATE = "validate"
    DISPATCH = "dispatch"
    EXECUTE = "execute"
    SYNTHESIZE = "synthesize"
    GOVERNANCE = "governance"
    RECEIPT = "receipt"
    TERMINAL = "terminal"


class IntakeEnvelope(BaseModel):
    request_id: str
    raw_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    normalized_text: str = ""


class IntentClassification(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class ExecutionStep(BaseModel):
    step_id: str
    title: str
    executor: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    plan_id: str
    steps: list[ExecutionStep] = Field(default_factory=list)
    rationale: str = ""


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: str = "error"
    path: str | None = None


class ValidationReport(BaseModel):
    validator_id: str
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ExecutionArtifact(BaseModel):
    step_id: str
    executor: str
    output: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)

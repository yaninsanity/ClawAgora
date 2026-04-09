from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from clawagora.contracts.task import ExecutionArtifact


class StagedRun(BaseModel):
    stage_id: str
    checkpoint: bool = False


class RollbackPlan(BaseModel):
    task_id: str
    steps: list[StagedRun] = Field(default_factory=list)


def build_rollback_plan(task_id: str, artifacts: "list[ExecutionArtifact]") -> RollbackPlan:
    """Build a RollbackPlan from the completed execution artifacts.

    Each artifact maps to a StagedRun checkpoint so operators can identify
    which steps completed and derive compensating actions if needed.
    """
    return RollbackPlan(
        task_id=task_id,
        steps=[StagedRun(stage_id=a.step_id, checkpoint=True) for a in artifacts],
    )

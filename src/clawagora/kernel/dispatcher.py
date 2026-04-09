from __future__ import annotations

from pydantic import BaseModel

from clawagora.contracts.task import ExecutionStep, Plan


class DispatchAssignment(BaseModel):
    step_id: str
    executor: str
    governance_role: str = "General Coordinator"
    governance_weight: float = 1.0


class Dispatcher:
    """Assigns plan steps to executor instances.

    Passes through the executor choice made by PlannerService verbatim.
    One assignment per plan step — ordering is preserved.
    """

    def assign(self, plan: Plan) -> list[DispatchAssignment]:
        indexed: list[tuple[int, DispatchAssignment]] = []
        for idx, step in enumerate(plan.steps):
            role = str(step.inputs.get("governance_role") or "General Coordinator")
            raw_weight = step.inputs.get("governance_weight", 1.0)
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                weight = 1.0
            indexed.append(
                (
                    idx,
                    DispatchAssignment(
                        step_id=step.step_id,
                        executor=step.executor,
                        governance_role=role,
                        governance_weight=weight,
                    ),
                )
            )
        indexed.sort(key=lambda x: (-x[1].governance_weight, x[0]))
        return [item[1] for item in indexed]

    def ordered_steps(self, plan: Plan) -> list[ExecutionStep]:
        return list(plan.steps)

from __future__ import annotations

import uuid

from clawagora.contracts.task import ExecutionStep, IntentClassification, IntakeEnvelope, Plan
from clawagora.governance.profile import build_governance_context
from clawagora.packs.registry import PackId, PackRegistry


class PlannerService:
    """Builds an execution plan whose executor sequence is driven by intent classification.

    The mapping from classification label → PackId selects the executor list
    from PackRegistry, so domain packs directly control pipeline shape without
    touching planner logic.
    """

    _LABEL_TO_PACK: dict[str, str] = {
        "engineering": PackId.CODING,
        "research": PackId.RESEARCH,
        "support": PackId.SUPPORT,
    }

    def __init__(self, registry: PackRegistry | None = None) -> None:
        self._registry = registry or PackRegistry()

    def plan(self, envelope: IntakeEnvelope, classification: IntentClassification) -> Plan:
        plan_id = str(uuid.uuid4())
        pack_id = self._LABEL_TO_PACK.get(classification.label)
        governance = build_governance_context(envelope.metadata)

        if pack_id is not None:
            executors: list[str] = self._registry.describe(pack_id).get("executors") or [
                "executor_transform",
                "executor_echo",
            ]
        else:
            executors = ["executor_transform", "executor_echo"]

        # Every executor receives both raw text and the resolved intent label so
        # domain executors (coding/research/support) can use whichever they need
        # without requiring planner-level field routing logic.
        step_inputs = {
            "text": envelope.normalized_text,
            "intent": classification.label,
        }
        steps: list[ExecutionStep] = []
        for i, ex in enumerate(executors):
            role = governance.role_for_step(i)
            inputs = dict(step_inputs)
            inputs["governance_profile"] = governance.profile
            inputs["governance_role"] = role
            inputs["governance_weight"] = governance.weight_for_role(role)
            steps.append(
                ExecutionStep(
                    step_id=f"{plan_id}-s{i + 1}",
                    title=self._step_title(ex, i),
                    executor=ex,
                    inputs=inputs,
                )
            )

        rationale = (
            "Intent="
            f"{classification.label}; pack={pack_id or 'default'}; profile={governance.profile}; "
            f"steps={len(steps)}"
        )
        return Plan(plan_id=plan_id, steps=steps, rationale=rationale)

    @staticmethod
    def _step_title(executor: str, index: int) -> str:
        _TITLES = {
            "executor_transform": "Gather context",
            "executor_echo": "Produce structured output",
            "executor_coding": "Analyze code",
            "executor_research": "Retrieve research",
            "executor_support": "Build support ticket",
        }
        return _TITLES.get(executor, f"Step {index + 1}")

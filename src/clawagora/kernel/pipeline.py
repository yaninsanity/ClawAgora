from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from clawagora.contracts.task import (
    ExecutionArtifact,
    IntentClassification,
    IntakeEnvelope,
    Plan,
    TaskPhase,
    TaskState,
    ValidationReport,
)
from clawagora.kernel.classify import ClassifyService
from clawagora.kernel.dispatcher import Dispatcher, DispatchAssignment
from clawagora.kernel.executors.base import ExecutorRegistry
from clawagora.kernel.intake import IntakeService
from clawagora.kernel.planner import PlannerService
from clawagora.kernel.synthesizer import Synthesizer
from clawagora.kernel.validation import CompositeValidator

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    state: TaskState
    envelope: IntakeEnvelope
    classification: IntentClassification | None
    plan: Plan | None
    validation: list[ValidationReport]
    artifacts: list[ExecutionArtifact]
    synthesis: dict | None
    error: str | None = None
    error_type: str | None = None
    # Exact pipeline stage where failure occurred; set for both normal and
    # exceptional failures so callers never need to re-derive it.
    error_stage: str | None = None


class TaskPipeline:
    def __init__(
        self,
        intake: IntakeService,
        classify: ClassifyService,
        planner: PlannerService,
        validators: CompositeValidator,
        dispatcher: Dispatcher,
        registry: ExecutorRegistry,
        synthesizer: Synthesizer,
        *,
        max_workers: int = 8,
    ) -> None:
        self._intake = intake
        self._classify = classify
        self._planner = planner
        self._validators = validators
        self._dispatcher = dispatcher
        self._registry = registry
        self._synthesizer = synthesizer
        self._max_workers = max(1, max_workers)

    def run(
        self,
        raw_text: str,
        metadata: dict | None = None,
        *,
        request_id: str | None = None,
    ) -> PipelineResult:
        envelope = self._intake.accept(raw_text, metadata, request_id=request_id)

        # Partial pipeline outputs — preserved even when an unexpected
        # exception aborts execution mid-flight.
        classification: IntentClassification | None = None
        plan: Plan | None = None
        reports: list[ValidationReport] = []
        current_stage = TaskPhase.CLASSIFY.value

        try:
            classification = self._classify.classify(envelope)

            current_stage = TaskPhase.PLAN.value
            plan = self._planner.plan(envelope, classification)

            current_stage = TaskPhase.VALIDATE.value
            reports = self._validators.validate_all(envelope, classification, plan)
            if not all(r.passed for r in reports):
                return PipelineResult(
                    state=TaskState.FAILED,
                    envelope=envelope,
                    classification=classification,
                    plan=plan,
                    validation=reports,
                    artifacts=[],
                    synthesis=None,
                    error="validation_failed",
                    error_stage=TaskPhase.VALIDATE.value,
                )

            current_stage = TaskPhase.DISPATCH.value
            assignments = self._dispatcher.assign(plan)

            current_stage = TaskPhase.EXECUTE.value
            # Build lookup so workers can resolve step → executor without
            # iterating the plan list inside the thread.
            step_by_id = {s.step_id: s for s in plan.steps}

            def _run_assignment(a: DispatchAssignment) -> ExecutionArtifact:
                step = step_by_id[a.step_id]
                executor = self._registry.get(a.executor)
                return executor.run(step)

            artifacts: list[ExecutionArtifact] = []
            if len(assignments) > 1:
                # Independent steps are executed in parallel. A thread-safety
                # note: executors must not share mutable state; the built-in
                # executors satisfy this requirement.
                with ThreadPoolExecutor(max_workers=min(len(assignments), self._max_workers)) as pool:
                    futures = {pool.submit(_run_assignment, a): a for a in assignments}
                    # Preserve submission order for deterministic event logging.
                    ordered = {a.step_id: None for a in assignments}
                    for fut in as_completed(futures):
                        a = futures[fut]
                        ordered[a.step_id] = fut.result()  # re-raise on exception
                    artifacts = [ordered[a.step_id] for a in assignments]
            else:
                for a in assignments:
                    artifacts.append(_run_assignment(a))

            current_stage = TaskPhase.SYNTHESIZE.value
            synthesis = self._synthesizer.synthesize(envelope, classification, plan, artifacts)
            return PipelineResult(
                state=TaskState.COMPLETED,
                envelope=envelope,
                classification=classification,
                plan=plan,
                validation=reports,
                artifacts=artifacts,
                synthesis=synthesis,
            )
        except Exception as exc:
            logger.exception(
                "pipeline_execution_failed request_id=%s stage=%s",
                envelope.request_id,
                current_stage,
            )
            return PipelineResult(
                state=TaskState.FAILED,
                envelope=envelope,
                classification=classification,
                plan=plan,
                validation=reports,
                artifacts=[],
                synthesis=None,
                error="pipeline_execution_failed",
                error_type=type(exc).__name__,
                error_stage=current_stage,
            )

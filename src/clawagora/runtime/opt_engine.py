from __future__ import annotations

from clawagora.config import OPTIMIZATION_CONFIG
from clawagora.contracts.task import IntentClassification, ValidationReport
from clawagora.runtime.optimization import OptimizationRecommendation, OptimizationReport


class OptimizationEngine:
    """Analyses pipeline execution metrics and produces actionable recommendations.

    Checks performed:
      LOW_CLASSIFICATION_CONFIDENCE
        Classification confidence below 0.65 signals ambiguous input; callers
        should add domain-specific keywords to improve routing accuracy.
      HIGH_STEP_COUNT
        More than 4 execution steps is a candidate for pack-level batching.
      VALIDATION_WARNINGS
        Any validator that did not fully pass is surfaced here for operator
        awareness even when the task ultimately succeeded.
    """

    _CONFIDENCE_THRESHOLD: float = OPTIMIZATION_CONFIG.confidence_threshold
    _STEP_COUNT_THRESHOLD: int = OPTIMIZATION_CONFIG.step_count_threshold

    def analyze(
        self,
        *,
        task_id: str,
        classification: IntentClassification | None,
        validation: list[ValidationReport],
        artifact_count: int,
    ) -> OptimizationReport:
        items: list[OptimizationRecommendation] = []

        if classification is not None and classification.confidence < self._CONFIDENCE_THRESHOLD:
            items.append(
                OptimizationRecommendation(
                    code="LOW_CLASSIFICATION_CONFIDENCE",
                    message=(
                        f"Classification confidence {classification.confidence:.2f} is below "
                        f"threshold {self._CONFIDENCE_THRESHOLD:.2f}. "
                        "Consider adding domain-specific keywords to improve routing accuracy."
                    ),
                    severity="warning",
                )
            )

        if artifact_count > self._STEP_COUNT_THRESHOLD:
            items.append(
                OptimizationRecommendation(
                    code="HIGH_STEP_COUNT",
                    message=(
                        f"Pipeline executed {artifact_count} steps. "
                        "Review whether all steps are necessary or could be batched."
                    ),
                    severity="info",
                )
            )

        failed_validators = [r.validator_id for r in validation if not r.passed]
        if failed_validators:
            items.append(
                OptimizationRecommendation(
                    code="VALIDATION_WARNINGS",
                    message=(
                        f"Validators that did not fully pass: {failed_validators}. "
                        "Inspect validation_reports for issue details."
                    ),
                    severity="warning",
                )
            )

        return OptimizationReport(task_id=task_id, items=items)

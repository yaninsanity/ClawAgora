from __future__ import annotations

from clawagora.config import TRUST_CONFIG
from clawagora.contracts.task import IntentClassification, ValidationReport
from clawagora.runtime.trust import TrustScore


class TrustScoreComputer:
    """Derives a TrustScore from classification confidence and validation results.

    Scoring algorithm:
      - Base value = classification.confidence (0.0 – 1.0); default 0.5 when absent.
      - All validators passed  → +0.10 bonus, capped at 1.0.
      - Each failed validator  → −0.15 penalty, floored at 0.0.
      - Final value is rounded to 4 decimal places.
    """

    def compute(
        self,
        classification: IntentClassification | None,
        validation: list[ValidationReport],
    ) -> TrustScore:
        base = (
            classification.confidence
            if classification is not None
            else TRUST_CONFIG.default_base_score
        )
        reasons: list[str] = []

        if classification is not None:
            reasons.append(f"intent:{classification.label}@{classification.confidence:.2f}")

        all_passed = all(r.passed for r in validation) if validation else True
        if all_passed:
            score = min(base + TRUST_CONFIG.all_passed_bonus, TRUST_CONFIG.max_score)
            reasons.append("all_validators_passed")
        else:
            failed = [r.validator_id for r in validation if not r.passed]
            penalty = len(failed) * TRUST_CONFIG.failed_validator_penalty
            score = max(base - penalty, TRUST_CONFIG.min_score)
            reasons.extend(f"validator_failed:{v}" for v in failed)

        return TrustScore(value=round(score, 4), reasons=reasons)

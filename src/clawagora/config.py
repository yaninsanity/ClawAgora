from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GovernanceLevelPolicy:
    window: float
    half_life_days: float
    lifecycle_shift_cap: float
    apply_alpha: float
    max_step_change: float


@dataclass(frozen=True, slots=True)
class GovernanceConfig:
    default_role_weight: float = 1.0
    weight_min: float = 0.2
    weight_max: float = 2.0
    incident_penalty_per_case: float = 0.08


@dataclass(frozen=True, slots=True)
class AccountabilityConfig:
    success_role_delta: float = 0.03
    success_audit_delta: float = 0.05
    validate_compliance_delta: float = 0.08
    validate_review_delta: float = 0.05
    validate_drafter_delta: float = -0.06
    execute_dispatch_delta: float = -0.08
    execute_lead_delta: float = -0.05
    fallback_intake_delta: float = -0.04
    default_feedback_max_items: int = 64
    reason_max_length: int = 256
    delta_min: float = -1.0
    delta_max: float = 1.0


@dataclass(frozen=True, slots=True)
class ClassificationConfig:
    default_model_confidence: float = 0.7
    support_confidence: float = 0.71
    research_confidence: float = 0.74
    engineering_confidence: float = 0.78
    general_confidence: float = 0.62
    confidence_min: float = 0.0
    confidence_max: float = 1.0


@dataclass(frozen=True, slots=True)
class OptimizationConfig:
    confidence_threshold: float = 0.65
    step_count_threshold: int = 4


@dataclass(frozen=True, slots=True)
class TrustConfig:
    default_base_score: float = 0.5
    all_passed_bonus: float = 0.10
    failed_validator_penalty: float = 0.15
    min_score: float = 0.0
    max_score: float = 1.0


@dataclass(frozen=True, slots=True)
class DomainExecutorConfig:
    coding_keyword_min_length: int = 5
    coding_keyword_limit: int = 10
    coding_complexity_medium_token_count: int = 30
    coding_complexity_high_token_count: int = 80
    research_keyword_min_length: int = 6
    research_keyword_limit: int = 8
    research_summary_char_limit: int = 300
    support_priority_medium_word_count: int = 15
    support_priority_high_word_count: int = 50
    support_safe_output_char_limit: int = 200


GOVERNANCE_CONFIG = GovernanceConfig()
ACCOUNTABILITY_CONFIG = AccountabilityConfig()
CLASSIFICATION_CONFIG = ClassificationConfig()
OPTIMIZATION_CONFIG = OptimizationConfig()
TRUST_CONFIG = TrustConfig()
DOMAIN_EXECUTOR_CONFIG = DomainExecutorConfig()

GOVERNANCE_LEVEL_POLICIES: dict[str, GovernanceLevelPolicy] = {
    "minimal": GovernanceLevelPolicy(
        window=6.0,
        half_life_days=20.0,
        lifecycle_shift_cap=1.0,
        apply_alpha=1.0,
        max_step_change=0.45,
    ),
    "balanced": GovernanceLevelPolicy(
        window=12.0,
        half_life_days=45.0,
        lifecycle_shift_cap=0.8,
        apply_alpha=0.6,
        max_step_change=0.25,
    ),
    "strict": GovernanceLevelPolicy(
        window=20.0,
        half_life_days=90.0,
        lifecycle_shift_cap=0.5,
        apply_alpha=0.35,
        max_step_change=0.15,
    ),
}

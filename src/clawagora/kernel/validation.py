from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable

from clawagora.contracts.task import (
    IntentClassification,
    IntakeEnvelope,
    Plan,
    ValidationIssue,
    ValidationReport,
)


class Validator(ABC):
    @property
    @abstractmethod
    def validator_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def validate(
        self,
        envelope: IntakeEnvelope,
        classification: IntentClassification,
        plan: Plan,
    ) -> ValidationReport:
        raise NotImplementedError


class SchemaValidator(Validator):
    @property
    def validator_id(self) -> str:
        return "schema"

    def validate(
        self,
        envelope: IntakeEnvelope,
        classification: IntentClassification,
        plan: Plan,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if not envelope.normalized_text:
            issues.append(ValidationIssue(code="EMPTY_INPUT", message="Normalized text is empty"))
        if not plan.steps:
            issues.append(ValidationIssue(code="EMPTY_PLAN", message="Plan has no steps"))
        for step in plan.steps:
            if not step.executor:
                issues.append(
                    ValidationIssue(
                        code="MISSING_EXECUTOR",
                        message=f"Step {step.step_id} has no executor",
                        path=step.step_id,
                    )
                )
        passed = len(issues) == 0
        return ValidationReport(validator_id=self.validator_id, passed=passed, issues=issues)


class PolicyValidator(Validator):
    # All built-in executors (generic + domain) are allowed by default.
    # Pass an explicit set to restrict to a subset for a specific pack.
    _DEFAULT_ALLOWED: frozenset[str] = frozenset(
        {
            "executor_transform",
            "executor_echo",
            "executor_coding",
            "executor_research",
            "executor_support",
        }
    )

    def __init__(
        self,
        allowed_executors: set[str] | None = None,
        *,
        policy_loader: Callable[[], set[str] | None] | None = None,
    ) -> None:
        self._static = frozenset(allowed_executors) if allowed_executors else self._DEFAULT_ALLOWED
        self._loader = policy_loader

    def _allowed_set(self) -> frozenset[str]:
        if self._loader is not None:
            dynamic = self._loader()
            if dynamic is not None:
                return frozenset(dynamic)
        return self._static

    @property
    def validator_id(self) -> str:
        return "policy"

    def validate(
        self,
        envelope: IntakeEnvelope,
        classification: IntentClassification,
        plan: Plan,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        allowed = self._allowed_set()
        for step in plan.steps:
            if step.executor not in allowed:
                issues.append(
                    ValidationIssue(
                        code="EXECUTOR_NOT_ALLOWED",
                        message=f"Executor not permitted: {step.executor}",
                        path=step.step_id,
                    )
                )
        passed = len(issues) == 0
        return ValidationReport(validator_id=self.validator_id, passed=passed, issues=issues)


class SafetyValidator(Validator):
    def __init__(
        self,
        deny_patterns: list[str] | None = None,
        *,
        deny_loader: Callable[[], list[str] | None] | None = None,
    ) -> None:
        self._static_deny = deny_patterns or [
            r"\bsecret\b",
            r"\bpassword\b",
            r"\bapi[_-]?key\b",
        ]
        self._loader = deny_loader

    def _deny_patterns(self) -> list[str]:
        if self._loader is not None:
            dynamic = self._loader()
            if dynamic is not None:
                return dynamic
        return self._static_deny

    @property
    def validator_id(self) -> str:
        return "safety"

    def validate(
        self,
        envelope: IntakeEnvelope,
        classification: IntentClassification,
        plan: Plan,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        text = envelope.normalized_text.lower()
        for pat in self._deny_patterns():
            if re.search(pat, text):
                issues.append(
                    ValidationIssue(
                        code="DENIED_PATTERN",
                        message=f"Input matches a deny pattern: {pat!r}",
                        severity="error",
                    )
                )
                break
        passed = len(issues) == 0
        return ValidationReport(
            validator_id=self.validator_id,
            passed=passed,
            issues=issues,
            metrics={"patterns_checked": len(self._deny_patterns())},
        )


class CompositeValidator:
    def __init__(self, validators: list[Validator]) -> None:
        self._validators = validators

    def validate_all(
        self,
        envelope: IntakeEnvelope,
        classification: IntentClassification,
        plan: Plan,
    ) -> list[ValidationReport]:
        return [v.validate(envelope, classification, plan) for v in self._validators]

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from clawagora.config import CLASSIFICATION_CONFIG
from clawagora.contracts.task import IntentClassification, IntakeEnvelope
from clawagora.cost import CostPolicy, estimate_cost_usd, estimate_tokens
from clawagora.prompts import PromptVersion, resolve_prompt
from clawagora.providers.base import ModelProvider

logger = logging.getLogger(__name__)


@dataclass
class ClassifyRule:
    """A single regex-based classification rule for the fallback classifier.

    Attributes:
        label:      The intent label to assign when *pattern* matches.
        pattern:    A regex string (compiled with re.IGNORECASE).
        confidence: Confidence score to report when this rule wins.
        priority:   Rules are evaluated in descending priority order (higher = earlier).
                    Ties are resolved by insertion order.
    """

    label: str
    pattern: str
    confidence: float
    priority: int = 0
    _compiled: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._compiled = re.compile(self.pattern, re.IGNORECASE)

    def matches(self, text: str) -> bool:
        return bool(self._compiled.search(text))


# Module-level registry: ordered list of ClassifyRule (high priority first).
# Built-in rules are seeded at import time; downstream code can call
# register_classify_rule() to extend or override without forking this module.
_CLASSIFY_RULES: list[ClassifyRule] = [
    ClassifyRule(
        label="support",
        pattern=r"\b(ticket|customer|support|sla)\b",
        confidence=CLASSIFICATION_CONFIG.support_confidence,
        priority=30,
    ),
    ClassifyRule(
        label="research",
        pattern=r"\b(research|paper|cite|summary)\b",
        confidence=CLASSIFICATION_CONFIG.research_confidence,
        priority=20,
    ),
    ClassifyRule(
        label="engineering",
        pattern=r"\b(code|bug|refactor|repo|api|test)\b",
        confidence=CLASSIFICATION_CONFIG.engineering_confidence,
        priority=10,
    ),
]
# Sorted descending by priority so that higher-priority rules are tested first.
_CLASSIFY_RULES.sort(key=lambda r: r.priority, reverse=True)

# The set of labels that the model classifier may return.  Updated whenever
# a new rule is registered via register_classify_rule().
_VALID_LABELS: set[str] = {r.label for r in _CLASSIFY_RULES} | {"general"}


def register_classify_rule(rule: ClassifyRule) -> None:
    """Register a custom classification rule at runtime.

    The new rule is inserted in priority order.  Its label is automatically
    added to the valid-label set used by the LLM classifier so model outputs
    that return the new label are accepted rather than falling back to "general".

    Example::

        from clawagora.kernel.classify import ClassifyRule, register_classify_rule
        register_classify_rule(ClassifyRule(
            label="legal",
            pattern=r"\\b(contract|clause|gdpr|compliance)\\b",
            confidence=0.75,
            priority=25,
        ))
    """
    _CLASSIFY_RULES.append(rule)
    _CLASSIFY_RULES.sort(key=lambda r: r.priority, reverse=True)
    _VALID_LABELS.add(rule.label)


class ClassifyService:
    """Intent classifier with optional LLM backend.

    When *model* is provided and returns a valid JSON response, the
    model-driven label and confidence are used.  If the model returns
    ``None`` or unparseable JSON, the service falls back to the
    deterministic regex baseline — so classification always succeeds.

    Inject an ``OllamaModelProvider`` or ``OpenAICompatProvider`` for
    semantic classification beyond keyword matching.
    """

    def __init__(
        self,
        model: ModelProvider | None = None,
        *,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self._model = model
        self._cost_policy = cost_policy

    def classify(self, envelope: IntakeEnvelope) -> IntentClassification:
        forced = envelope.metadata.get("prompt_forced_versions")
        forced_map = forced if isinstance(forced, dict) else {}
        prompt_tpl = resolve_prompt(
            "classify.system",
            context_id=envelope.request_id,
            forced_versions=forced_map or None,
        )
        trace = dict(envelope.metadata.get("prompt_trace") or {})
        trace["classify"] = {"prompt_key": prompt_tpl.key, "prompt_version": prompt_tpl.version}
        envelope.metadata["prompt_trace"] = trace
        if self._model is not None:
            result = self._classify_with_model(envelope, prompt_tpl=prompt_tpl)
            if result is not None:
                return result
        return self._classify_with_regex(envelope)

    def _classify_with_model(
        self, envelope: IntakeEnvelope, *, prompt_tpl: PromptVersion
    ) -> IntentClassification | None:
        raw = self._model.complete(  # type: ignore[union-attr]
            envelope.normalized_text,
            system=prompt_tpl.system,
            prompt_meta={"prompt_key": prompt_tpl.key, "prompt_version": prompt_tpl.version},
        )
        if not raw:
            return None
        # Strip optional markdown code fences that some models add.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(line for line in lines if not line.startswith("```")).strip()
        try:
            data = json.loads(cleaned)
            label = str(data.get("label", "general")).lower()
            if label not in _VALID_LABELS:
                label = "general"
            confidence = float(
                data.get("confidence", CLASSIFICATION_CONFIG.default_model_confidence)
            )
            confidence = max(
                CLASSIFICATION_CONFIG.confidence_min,
                min(CLASSIFICATION_CONFIG.confidence_max, confidence),
            )
            tags = [str(t) for t in data.get("tags", []) if isinstance(t, str)]
            self._append_llm_usage(
                envelope,
                prompt_tpl,
                envelope.normalized_text,
                cleaned,
            )
            return IntentClassification(label=label, confidence=confidence, tags=tags)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug("model_classify_parse_error: %s  raw=%r", exc, raw[:200])
            return None

    def _append_llm_usage(
        self,
        envelope: IntakeEnvelope,
        prompt_tpl: PromptVersion,
        prompt_text: str,
        response_text: str,
    ) -> None:
        if self._cost_policy is None:
            return
        policy = self._cost_policy
        tin = estimate_tokens(prompt_text, token_chars_estimate=policy.token_chars_estimate)
        tout = estimate_tokens(response_text or "", token_chars_estimate=policy.token_chars_estimate)
        est = estimate_cost_usd(tin, tout, policy=policy)
        usage = envelope.metadata.setdefault("llm_usage", [])
        usage.append(
            {
                "prompt_key": prompt_tpl.key,
                "prompt_version": prompt_tpl.version,
                "est_cost_usd": est,
            }
        )

    def _classify_with_regex(self, envelope: IntakeEnvelope) -> IntentClassification:
        text = envelope.normalized_text.lower()
        # Evaluate rules in priority order (highest first).
        # Only the first matching rule's tags are assigned so that
        # classification.tags always reflects the resolved label.
        for rule in _CLASSIFY_RULES:
            if rule.matches(text):
                return IntentClassification(
                    label=rule.label,
                    confidence=rule.confidence,
                    tags=[rule.label],
                )
        return IntentClassification(
            label="general", confidence=CLASSIFICATION_CONFIG.general_confidence, tags=[]
        )

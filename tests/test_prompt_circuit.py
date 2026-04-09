"""Prompt circuit breaker: metrics, trip, and forced prompt versions."""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import override_settings

from clawagora.contracts.task import IntakeEnvelope, TaskState
from clawagora.kernel.pipeline import PipelineResult
from clawagora.prompts import PROMPT_REGISTRY, PromptVersion
from orchestration.prompt_circuit import (
    merge_circuit_overrides_into_metadata,
    record_prompt_circuit_outcome,
)


def _failed_classify_result(*, version: str = "v1") -> PipelineResult:
    trace = {
        "classify": {"prompt_key": "classify.system", "prompt_version": version},
    }
    env = IntakeEnvelope(
        request_id="r1",
        raw_text="x",
        metadata={"prompt_trace": trace, "llm_usage": []},
        normalized_text="x",
    )
    return PipelineResult(
        state=TaskState.FAILED,
        envelope=env,
        classification=None,
        plan=None,
        validation=[],
        artifacts=[],
        synthesis=None,
        error="pipeline_execution_failed",
        error_stage="classify",
    )


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_PROMPT_CIRCUIT_ENABLED=True,
    CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES=1,
    CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX=0.5,
    CLAWAGORA_PROMPT_CIRCUIT_AVG_COST_USD_MAX=0.0,
)
def test_record_failure_trips_circuit_and_merge_forces_fallback():
    cache.clear()
    result = _failed_classify_result(version="v2")
    record_prompt_circuit_outcome(result, success=False)
    assert cache.get("prompt_circuit_open:classify.system") == "v1"

    md: dict = {}
    merge_circuit_overrides_into_metadata(md)
    assert md["prompt_forced_versions"]["classify.system"] == "v1"


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_PROMPT_CIRCUIT_ENABLED=True,
    CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES=2,
    CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX=0.5,
)
def test_circuit_requires_min_samples():
    cache.clear()
    result = _failed_classify_result(version="v2")
    record_prompt_circuit_outcome(result, success=False)
    assert cache.get("prompt_circuit_open:classify.system") is None

    record_prompt_circuit_outcome(result, success=False)
    assert cache.get("prompt_circuit_open:classify.system") == "v1"


def test_resolve_prompt_respects_forced_versions(monkeypatch):
    v1 = PromptVersion(
        key="classify.system",
        version="v1",
        rollout=50,
        system="A",
    )
    v2 = PromptVersion(
        key="classify.system",
        version="v2",
        rollout=50,
        system="B",
    )
    monkeypatch.setitem(PROMPT_REGISTRY, "classify.system", (v1, v2))
    from clawagora.prompts import resolve_prompt

    picked = resolve_prompt(
        "classify.system",
        context_id="req-001",
        forced_versions={"classify.system": "v2"},
    )
    assert picked.version == "v2"
    assert picked.system == "B"


@pytest.mark.django_db
@override_settings(
    CLAWAGORA_PROMPT_CIRCUIT_ENABLED=True,
    CLAWAGORA_PROMPT_CIRCUIT_MIN_SAMPLES=1,
    CLAWAGORA_PROMPT_CIRCUIT_ERROR_RATE_MAX=1.0,
    CLAWAGORA_PROMPT_CIRCUIT_AVG_COST_USD_MAX=0.00001,
)
def test_avg_cost_threshold_trips_circuit():
    cache.clear()
    trace = {
        "classify": {"prompt_key": "classify.system", "prompt_version": "v1"},
    }
    env = IntakeEnvelope(
        request_id="r1",
        raw_text="x",
        metadata={
            "prompt_trace": trace,
            "llm_usage": [{"prompt_key": "classify.system", "prompt_version": "v1", "est_cost_usd": 0.1}],
        },
        normalized_text="x",
    )
    result = PipelineResult(
        state=TaskState.COMPLETED,
        envelope=env,
        classification=None,
        plan=None,
        validation=[],
        artifacts=[],
        synthesis={"x": 1},
    )
    record_prompt_circuit_outcome(result, success=True)
    assert cache.get("prompt_circuit_open:classify.system") == "v1"

"""clawagora_context validation and delegate bundle extraction."""

import pytest
from rest_framework.serializers import ValidationError

from orchestration.metadata_context import (
    CLAWAGORA_CONTEXT_KEY,
    extract_delegate_context_bundle,
    merge_patch_task_metadata,
    normalize_task_metadata_clawagora_context,
    validate_clawagora_context,
)


def test_validate_clawagora_context_trims_and_orders():
    out = validate_clawagora_context(
        {
            "session_id": "  ws-1  ",
            "correlation_id": "t-9",
            "memory_refs": ["  a  ", "", "b"],
        }
    )
    assert out == {"session_id": "ws-1", "correlation_id": "t-9", "memory_refs": ["a", "b"]}


def test_validate_rejects_unknown_keys():
    with pytest.raises(ValueError, match="Unknown keys"):
        validate_clawagora_context({"session_id": "x", "extra": 1})


def test_validate_rejects_bad_memory_refs_type():
    with pytest.raises(ValueError, match="memory_refs"):
        validate_clawagora_context({"memory_refs": "not-a-list"})


def test_normalize_drops_empty_context():
    base = {"openclaw": {"delegate": True}, CLAWAGORA_CONTEXT_KEY: {}}
    out = normalize_task_metadata_clawagora_context(base)
    assert CLAWAGORA_CONTEXT_KEY not in out


def test_normalize_raises_validation_error():
    with pytest.raises(ValidationError):
        normalize_task_metadata_clawagora_context({CLAWAGORA_CONTEXT_KEY: {"memory_refs": [1, 2]}})


def test_extract_delegate_context_bundle():
    md = {
        CLAWAGORA_CONTEXT_KEY: {
            "session_id": "s1",
            "memory_refs": ["r1"],
        }
    }
    assert extract_delegate_context_bundle(md) == {"session_id": "s1", "memory_refs": ["r1"]}


def test_merge_patch_task_metadata_deep_merges_nested_dicts():
    base = {
        "clawagora_context": {"session_id": "sess-a"},
        "openclaw": {"delegate": True},
    }
    patch = {
        "clawagora_context": {"correlation_id": "c1"},
        "openclaw": {"agents": ["a1"]},
    }
    out = merge_patch_task_metadata(base, patch)
    assert out["clawagora_context"] == {"session_id": "sess-a", "correlation_id": "c1"}
    assert out["openclaw"] == {"delegate": True, "agents": ["a1"]}


def test_extract_delegate_context_bundle_sanitizes_garbage():
    md = {CLAWAGORA_CONTEXT_KEY: {"session_id": 123, "memory_refs": ["ok", 9, "  "]}}
    assert extract_delegate_context_bundle(md) == {"memory_refs": ["ok"]}

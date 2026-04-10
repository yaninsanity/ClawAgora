"""Unit tests for OpenClaw callback artifact normalization."""

import pytest

from orchestration.openclaw_callback_artifacts import normalize_openclaw_callback_artifacts


def test_normalize_empty_and_list():
    assert normalize_openclaw_callback_artifacts(None) == ([], None)
    out, err = normalize_openclaw_callback_artifacts([])
    assert out == [] and err is None


def test_normalize_accepts_text_alias():
    out, err = normalize_openclaw_callback_artifacts([{"role": "critic", "text": "nope"}])
    assert err is None
    assert out == [{"role": "critic", "content": "nope"}]


def test_normalize_rejects_non_list():
    _out, err = normalize_openclaw_callback_artifacts({})
    assert err == "artifacts must be a JSON array when present."


def test_normalize_rejects_non_object_element():
    _out, err = normalize_openclaw_callback_artifacts([1])
    assert err == "each artifact must be a JSON object."

import pytest
from django.core.exceptions import ImproperlyConfigured

from clawagora_server.env_parsing import (
    parse_execution_mode,
    parse_log_format,
    parse_log_level,
    parse_positive_int,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "sync"),
        ("", "sync"),
        ("sync", "sync"),
        ("SYNC", "sync"),
        ("  async  ", "async"),
    ],
)
def test_parse_execution_mode_accepts(raw, expected):
    assert parse_execution_mode(raw) == expected


@pytest.mark.parametrize("raw", ["both", "queue", "1", "realtime"])
def test_parse_execution_mode_rejects_invalid_strings(raw):
    with pytest.raises(ImproperlyConfigured):
        parse_execution_mode(raw)


def test_parse_positive_int_defaults_and_bounds():
    assert parse_positive_int("X", None, 42, minimum=1) == 42
    assert parse_positive_int("X", "", 42, minimum=1) == 42
    assert parse_positive_int("X", "  7 ", 1, minimum=1) == 7


def test_parse_positive_int_rejects_non_numeric():
    with pytest.raises(ImproperlyConfigured):
        parse_positive_int("X", "12.5", 1)


def test_parse_positive_int_rejects_below_minimum():
    with pytest.raises(ImproperlyConfigured):
        parse_positive_int("X", "0", 5, minimum=1)


def test_parse_log_level_accepts_info_case_insensitive():
    assert parse_log_level("info") == "INFO"
    assert parse_log_level(None) == "INFO"


def test_parse_log_level_rejects_garbage():
    with pytest.raises(ImproperlyConfigured):
        parse_log_level("VERBOSE")


def test_parse_log_format_accepts():
    assert parse_log_format("JSON") == "json"
    assert parse_log_format(None) == "text"


def test_parse_log_format_rejects():
    with pytest.raises(ImproperlyConfigured):
        parse_log_format("yaml")

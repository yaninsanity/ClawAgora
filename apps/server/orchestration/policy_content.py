"""Structured policy document validation — executable keys are explicit and auditable.

Natural-language-only rules are rejected as top-level keys; documentation may use
``_guide`` or ``_clawagora_*`` prefixes (not interpreted by validators).
"""

from __future__ import annotations

from typing import Any

# Keys enforced by PolicyValidator / SafetyValidator at execution time.
_EXECUTABLE_POLICY_KEYS = frozenset({"allowed_executors", "deny_patterns"})


def validate_policy_content_keys(content: dict[str, Any]) -> None:
    """Raise ValueError if *content* contains unknown top-level keys.

    Allowed:
    - ``allowed_executors``, ``deny_patterns`` (typed lists of strings elsewhere)
    - ``_guide`` — human-readable documentation only
    - any key starting with ``_clawagora_`` — seed/meta (not policy logic)
    """
    for key in content:
        if key in _EXECUTABLE_POLICY_KEYS:
            continue
        if key == "_guide":
            continue
        if key.startswith("_clawagora_"):
            continue
        raise ValueError(
            f"Unknown policy key {key!r}. Use only allowed_executors, deny_patterns, "
            "_guide, or _clawagora_* metadata — not free-form natural language rules."
        )

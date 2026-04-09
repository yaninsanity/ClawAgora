"""NullModelProvider — safe no-op default."""

from __future__ import annotations

from clawagora.providers.base import ModelProvider


class NullModelProvider(ModelProvider):
    """No-op provider that always returns ``None``.

    This is the default when no ``CLAWAGORA_MODEL_PROVIDER`` is configured.
    All kernel components that accept a ``ModelProvider`` will automatically
    fall back to their deterministic baseline (regex classification, template
    synthesis, etc.) when they receive ``None`` from ``complete()``.

    This ensures the system works out-of-the-box without any LLM backend,
    and operators can upgrade to a real provider at any time by setting env vars.
    """

    def complete(  # noqa: ARG002
        self,
        prompt: str,
        *,
        system: str | None = None,
        prompt_meta: dict[str, str] | None = None,
    ) -> str | None:
        return None

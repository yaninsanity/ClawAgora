"""ModelProvider ABC — the single extension point for LLM backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """Pluggable LLM backend.

    Implement this ABC once per model provider (Ollama, OpenAI-compatible,
    HuggingFace, Bedrock, …) and inject the instance into any kernel
    component that benefits from language-model reasoning.

    Contract
    --------
    * ``complete()`` returns the raw completion string on success.
    * ``complete()`` returns **None** when the provider is unavailable, the
      request times out, or any other non-fatal error occurs.  Callers **must**
      fall back to their deterministic baseline when ``None`` is returned —
      never let a provider error propagate to the task lifecycle.
    * Implementations are expected to be thread-safe (the orchestration service
      is a singleton shared across requests).
    """

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        prompt_meta: dict[str, str] | None = None,
    ) -> str | None:
        """Send *prompt* to the model and return the completion text.

        Parameters
        ----------
        prompt:
            The user-turn content to send.
        system:
            Optional system-turn / instruction preamble.  Providers that do
            not support a separate system turn should prepend it to the prompt.
        prompt_meta:
            Optional metadata about prompt routing (e.g. key/version) for
            observability logs. Providers may ignore it.

        Returns
        -------
        str
            Raw text returned by the model (stripped of surrounding whitespace).
        None
            Provider is unavailable or an error occurred; caller must fall back.
        """

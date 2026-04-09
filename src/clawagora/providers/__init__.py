"""Model provider adapters for ClawAgora.

Drop-in LLM backends that implement the ``ModelProvider`` ABC and can be
injected into any kernel component (ClassifyService, Synthesizer, …).

Available providers
-------------------
NullModelProvider      — no-op; callers fall back to deterministic baseline.
OllamaModelProvider    — Ollama REST API (gemma3, mistral, llama3, phi4, …).
OpenAICompatProvider   — any OpenAI-compatible endpoint (Ollama /v1, LM Studio,
                          llama.cpp, vLLM, Azure OpenAI, OpenAI API, …).

Usage (Python)
--------------
>>> from clawagora.providers.ollama import OllamaModelProvider
>>> provider = OllamaModelProvider(model_name="gemma3:4b")
>>> result = provider.complete("Classify: fix the authentication bug")

Usage (env-driven via Django settings)
---------------------------------------
Set CLAWAGORA_MODEL_PROVIDER=ollama, CLAWAGORA_MODEL_NAME=gemma3:4b.
``build_default_pipeline()`` in orchestration/services.py reads these settings
and injects the appropriate provider automatically.
"""

from clawagora.providers.base import ModelProvider
from clawagora.providers.null_provider import NullModelProvider

__all__ = ["ModelProvider", "NullModelProvider"]

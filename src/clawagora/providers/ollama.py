"""OllamaModelProvider — Ollama REST API backend.

Supports any model available in a local or remote Ollama installation:
``gemma4:latest``, ``gemma3:4b``, ``gemma3:27b``, ``mistral``, ``llama3``, ``phi4``, etc.

No extra Python packages are required — uses only stdlib ``urllib``.

Ollama install: https://ollama.com
Pull a model:  ``ollama pull gemma4:latest``
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from clawagora.cost import CostPolicy, estimate_cost_usd, estimate_tokens
from clawagora.providers.base import ModelProvider

logger = logging.getLogger(__name__)


class OllamaModelProvider(ModelProvider):
    """Calls the Ollama ``/api/generate`` endpoint (non-streaming).

    Parameters
    ----------
    base_url:
        Ollama server base URL.  Default: ``http://localhost:11434``.
        Override with ``CLAWAGORA_MODEL_URL`` when running in Docker/remote.
    model_name:
        Ollama model tag.  Default: ``gemma4:latest``.
        Override with ``CLAWAGORA_MODEL_NAME``.
    timeout_secs:
        Per-request timeout in seconds.  Default: 30.
        Override with ``CLAWAGORA_MODEL_TIMEOUT_SECS``.

    Ollama model examples
    ---------------------
    gemma4:latest    — Google Gemma 4 family (recommended when available)
    gemma3:4b        — Google Gemma 3 4B (fast, efficient)
    gemma3:27b       — Google Gemma 3 27B (higher quality)
    mistral          — Mistral 7B
    llama3:8b        — Meta Llama 3 8B
    phi4             — Microsoft Phi-4
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "gemma4:latest",
        timeout_secs: int = 30,
        temperature: float = 0.0,
        max_tokens: int = 512,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/api/generate"
        self._model = model_name
        self._timeout = timeout_secs
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._cost_policy = cost_policy or CostPolicy()

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        prompt_meta: dict[str, str] | None = None,
    ) -> str | None:
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_predict": self._max_tokens,
            },
        }
        if system:
            payload["system"] = system

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
            text = json.loads(raw).get("response") or ""
            in_tokens = estimate_tokens(
                f"{system or ''}\n{prompt}",
                token_chars_estimate=self._cost_policy.token_chars_estimate,
            )
            out_tokens = estimate_tokens(
                text, token_chars_estimate=self._cost_policy.token_chars_estimate
            )
            est_cost = estimate_cost_usd(in_tokens, out_tokens, policy=self._cost_policy)
            logger.info(
                "ollama_provider_usage model=%s prompt_key=%s prompt_version=%s input_tokens=%s output_tokens=%s est_cost_usd=%s",
                self._model,
                (prompt_meta or {}).get("prompt_key", ""),
                (prompt_meta or {}).get("prompt_version", ""),
                in_tokens,
                out_tokens,
                est_cost,
            )
            return text.strip() or None
        except urllib.error.URLError as exc:
            logger.warning(
                "ollama_provider_unavailable model=%s url=%s error=%s",
                self._model,
                self._url,
                exc,
            )
            return None
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("ollama_provider_parse_error model=%s error=%s", self._model, exc)
            return None

"""OpenAICompatProvider — any OpenAI-compatible chat completion endpoint.

Works with:
  - Ollama  (``http://localhost:11434/v1``)
  - LM Studio (``http://localhost:1234/v1``)
  - llama.cpp HTTP server (``http://localhost:8080/v1``)
  - vLLM
  - Azure OpenAI
  - OpenAI API itself (``https://api.openai.com``)
  - Any endpoint that accepts ``POST /v1/chat/completions``

No extra Python packages required — uses only stdlib ``urllib``.

Gemma via Ollama example
------------------------
Set ``CLAWAGORA_MODEL_PROVIDER=openai_compat``,
    ``CLAWAGORA_MODEL_URL=http://localhost:11434``,
    ``CLAWAGORA_MODEL_NAME=gemma4:latest``  (or another local tag, e.g. gemma3:27b)

The ``api_key`` is sent as a Bearer token in the ``Authorization`` header.
Leave empty for local servers that don't require authentication.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from clawagora.cost import CostPolicy, estimate_cost_usd, estimate_tokens
from clawagora.providers.base import ModelProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(ModelProvider):
    """Calls any OpenAI-compatible ``/v1/chat/completions`` endpoint.

    Parameters
    ----------
    base_url:
        Server base URL **without** a trailing path.
        For Ollama: ``http://localhost:11434``
        For OpenAI: ``https://api.openai.com``
        Override with ``CLAWAGORA_MODEL_URL``.
    model_name:
        Model identifier as recognized by the endpoint.
        Override with ``CLAWAGORA_MODEL_NAME``.
    api_key:
        Bearer token / API key.  Pass empty string for local servers.
        Override with ``CLAWAGORA_MODEL_API_KEY``.
    timeout_secs:
        Per-request timeout.  Default: 30.
        Override with ``CLAWAGORA_MODEL_TIMEOUT_SECS``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "gemma4:latest",
        api_key: str = "",
        timeout_secs: int = 30,
        temperature: float = 0.0,
        max_tokens: int = 512,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/v1/chat/completions"
        self._model = model_name
        self._api_key = api_key
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
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        req = urllib.request.Request(
            self._url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"] or ""
            in_tokens = estimate_tokens(
                f"{system or ''}\n{prompt}",
                token_chars_estimate=self._cost_policy.token_chars_estimate,
            )
            out_tokens = estimate_tokens(
                text, token_chars_estimate=self._cost_policy.token_chars_estimate
            )
            est_cost = estimate_cost_usd(in_tokens, out_tokens, policy=self._cost_policy)
            logger.info(
                "openai_compat_usage model=%s prompt_key=%s prompt_version=%s input_tokens=%s output_tokens=%s est_cost_usd=%s",
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
                "openai_compat_provider_unavailable model=%s url=%s error=%s",
                self._model,
                self._url,
                exc,
            )
            return None
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("openai_compat_provider_parse_error model=%s error=%s", self._model, exc)
            return None

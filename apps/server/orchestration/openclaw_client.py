"""Optional HTTP probe toward an OpenClaw-compatible gateway (Phase 3 integration)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OpenClawProbeResult:
    enabled: bool
    gateway_url: str
    reachable: bool
    http_status: int | None
    latency_ms: float | None
    detail: str
    body_preview: dict[str, Any] | None


def probe_gateway(
    *,
    gateway_url: str,
    api_key: str = "",
    timeout_sec: float = 3.0,
) -> OpenClawProbeResult:
    """GET {gateway_url}/health or / — best-effort liveness for operator dashboards."""
    import time

    base = gateway_url.rstrip("/")
    for path in ("/health", "/"):
        url = base + path
        t0 = time.perf_counter()
        req = urllib.request.Request(url, method="GET")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read()[:4000]
                latency_ms = (time.perf_counter() - t0) * 1000.0
                try:
                    preview = json.loads(raw.decode("utf-8", errors="replace"))
                    if not isinstance(preview, dict):
                        preview = {"raw": str(preview)[:500]}
                except json.JSONDecodeError:
                    preview = {"text": raw.decode("utf-8", errors="replace")[:500]}
                return OpenClawProbeResult(
                    enabled=True,
                    gateway_url=base,
                    reachable=True,
                    http_status=getattr(resp, "status", None) or resp.getcode(),
                    latency_ms=round(latency_ms, 2),
                    detail=f"ok ({path})",
                    body_preview=preview,
                )
        except urllib.error.HTTPError as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            if exc.code in (404,) and path == "/health":
                continue
            return OpenClawProbeResult(
                enabled=True,
                gateway_url=base,
                reachable=False,
                http_status=exc.code,
                latency_ms=round(latency_ms, 2),
                detail=f"http_error {exc.code} ({path})",
                body_preview=None,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.debug("openclaw_probe_fail url=%s err=%s", url, exc)
            return OpenClawProbeResult(
                enabled=True,
                gateway_url=base,
                reachable=False,
                http_status=None,
                latency_ms=round(latency_ms, 2),
                detail=str(exc)[:500],
                body_preview=None,
            )
    return OpenClawProbeResult(
        enabled=True,
        gateway_url=base,
        reachable=False,
        http_status=None,
        latency_ms=None,
        detail="no_health_endpoint",
        body_preview=None,
    )

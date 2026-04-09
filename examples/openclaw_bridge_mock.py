"""Minimal OpenClaw bridge mock for end-to-end integration testing.

Flow:
1) ClawAgora POSTs delegate payload to /delegate
2) This bridge simulates multi-agent work
3) Bridge POSTs signed callback back to ClawAgora

This script uses only Python stdlib.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "18791"))
WEBHOOK_SECRET = os.environ.get("CLAWAGORA_OPENCLAW_WEBHOOK_SECRET", "").strip()
SIMULATED_DELAY_MS = int(os.environ.get("BRIDGE_SIMULATED_DELAY_MS", "300"))
DEFAULT_STATUS = os.environ.get("BRIDGE_DEFAULT_STATUS", "completed").strip().lower()


def _sign(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _post_callback(callback_url: str, payload: dict) -> tuple[bool, int | None, str]:
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        callback_url,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-ClawAgora-Signature": _sign(WEBHOOK_SECRET, raw),
            "X-ClawAgora-Timestamp": str(int(time.time())),
            "X-ClawAgora-Nonce": hashlib.sha256(raw + str(time.time()).encode("utf-8")).hexdigest()[:32],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return (200 <= code < 300, code, "ok")
    except Exception as exc:  # noqa: BLE001
        return (False, None, str(exc))


def _background_execute(delegate: dict) -> None:
    time.sleep(max(SIMULATED_DELAY_MS, 0) / 1000.0)
    callback_url = str(delegate.get("callback_url") or "").strip()
    task_id = str(delegate.get("task_id") or "").strip()
    agents = delegate.get("agents") if isinstance(delegate.get("agents"), list) else []
    if not callback_url or not task_id or not WEBHOOK_SECRET:
        return
    if DEFAULT_STATUS == "failed":
        payload = {
            "task_id": task_id,
            "status": "failed",
            "error_code": "bridge_simulated_failure",
            "error": "Simulated by openclaw_bridge_mock.",
            "external_id": f"mock-{task_id[:8]}",
            "agents": agents,
        }
    else:
        payload = {
            "task_id": task_id,
            "status": "completed",
            "synthesis": {
                "summary": "Bridge simulated multi-agent completion.",
                "artifacts": [],
            },
            "external_id": f"mock-{task_id[:8]}",
            "agents": agents,
        }
    ok, code, detail = _post_callback(callback_url, payload)
    print(f"[bridge] callback task={task_id} ok={ok} code={code} detail={detail}")


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/delegate":
            self._reply(404, {"detail": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                self._reply(400, {"detail": "body must be object"})
                return
            if str(data.get("schema") or "") != "clawagora.openclaw.delegate.v1":
                self._reply(400, {"detail": "invalid schema"})
                return
            task_id = str(data.get("task_id") or "").strip()
            callback_url = str(data.get("callback_url") or "").strip()
            if not task_id or not callback_url:
                self._reply(400, {"detail": "task_id and callback_url are required"})
                return
            threading.Thread(target=_background_execute, args=(data,), daemon=True).start()
            self._reply(
                202,
                {
                    "accepted": True,
                    "task_id": task_id,
                    "message": "delegate accepted, callback scheduled",
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._reply(500, {"detail": str(exc)})

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(f"[bridge] {self.address_string()} - {fmt % args}")


def main() -> None:
    if not WEBHOOK_SECRET:
        raise SystemExit("CLAWAGORA_OPENCLAW_WEBHOOK_SECRET is required for signed callback.")
    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), Handler)
    print(f"[bridge] listening on http://{BRIDGE_HOST}:{BRIDGE_PORT}/delegate")
    server.serve_forever()


if __name__ == "__main__":
    main()

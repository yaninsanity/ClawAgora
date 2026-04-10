#!/usr/bin/env bash
# Local quality gate: Python tests + Ruff + web production build.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="python3"
fi

echo "== pytest (${PY}) =="
"${PY}" -m pytest tests/ -q

echo "== ruff =="
"${PY}" -m ruff check src apps/server tests

echo "== web build =="
cd web
npm run build

echo "OK"

#!/usr/bin/env bash
# Local CI gate: lint, format, tests.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
export PYTHONPATH="${ROOT}/src:${ROOT}/apps/server"
ruff check src apps/server tests
ruff format --check src apps/server tests
pytest -q tests/

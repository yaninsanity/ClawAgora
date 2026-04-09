#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}/src:${ROOT}/apps/server"
export DJANGO_SETTINGS_MODULE="clawagora_server.settings"

cd "${ROOT}/apps/server"
exec python manage.py runserver 0.0.0.0:8000

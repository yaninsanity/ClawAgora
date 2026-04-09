# Contributing to ClawAgora

Thank you for contributing. This project follows a small, focused set of practices so changes stay reviewable and safe.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[server,async,dev]"
```

Run the API locally:

```bash
export PYTHONPATH="$(pwd)/src:$(pwd)/apps/server"
export DJANGO_SETTINGS_MODULE=clawagora_server.settings
python apps/server/manage.py migrate
bash scripts/dev.sh
```

Run tests:

```bash
export PYTHONPATH="$(pwd)/src:$(pwd)/apps/server"
pytest -q
```

Build the web UI:

```bash
cd web && npm ci && npm run build
```

## Pull requests

- Keep changes scoped to one concern per PR.
- Add or update tests when behavior changes.
- Use English for commit messages, code comments, and documentation.
- Run `pytest` and `scripts/check-quality.sh` (if available) before submitting.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

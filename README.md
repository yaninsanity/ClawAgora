# ClawAgora

ClawAgora is an open-source control plane and kernel for governed task execution: intake, classification, planning, composite validation, dispatch, execution, synthesis, and durable receipts.

## Why Agora

The original Agora was a public space for deliberation, accountability, and civic coordination.
ClawAgora applies that principle to agent systems:

- Decisions are visible (`timeline`, `receipt`, `governance` events).
- Roles are explicit (intake, policy drafting, review, dispatch, audit).
- Governance is adaptive but bounded (weights, lifecycle guards, daily budget, rollback).
- Operators can intervene safely (`feedback`, `apply-recommendations`, `rollback`, dashboard).

Instead of black-box "agents talking to agents", ClawAgora emphasizes auditable governance loops for production operations.

## Components

- **Python library (`src/clawagora`)**: portable kernel, contracts, optional governance and runtime extension points.
- **Django service (`apps/server`)**: persistence, HTTP API, static hosting of the production UI bundle.
- **Web UI (`web`)**: TypeScript + React task submission and timeline visualization.

## Requirements

- Python 3.11+
- Node.js 18+ (for UI builds)

## Install (library)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[server,dev]"
```

Optional async worker (Redis + django-rq):

```bash
pip install -e ".[server,async,dev]"
```

## Python dependency management

Python dependencies are managed in `pyproject.toml`:

- core runtime: `[project.dependencies]`
- server stack: `[project.optional-dependencies].server`
- async worker stack: `[project.optional-dependencies].async`
- development tools: `[project.optional-dependencies].dev`

This project currently uses `pip install -e ".[...]"` from `pyproject.toml` and does
not maintain a separate `requirements.txt`.

## Database

Default development settings use SQLite at `apps/server/db.sqlite3`.

For PostgreSQL:

```bash
docker compose up -d
export POSTGRES_HOST=127.0.0.1
export POSTGRES_DB=clawagora
export POSTGRES_USER=clawagora
export POSTGRES_PASSWORD=clawagora
```

On first migrate, migration `0014_seed_starter_policy_draft` inserts an **inactive** draft named `starter-guide (seed)` so the Policies tab is not empty. It is safe to delete in the UI.

## Run API

**Precise first run**

1. **Python 3.11+** and **Node 18+** (Node only if you build the web UI).
2. `python3 -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
3. From the repo root: `pip install -e ".[server,dev]"` — add `async` in the extras list if you use RQ (`pip install -e ".[server,async,dev]"`).
4. Set env and migrate, then start the server (scripts default to `python3`; override with `PYTHON=...` if needed):

```bash
export PYTHONPATH="$(pwd)/src:$(pwd)/apps/server"
export DJANGO_SETTINGS_MODULE=clawagora_server.settings
python3 apps/server/manage.py migrate
bash scripts/dev.sh
```

5. API: **http://127.0.0.1:8000/api/v1/health/**  
6. **Optional UI**: `cd web && npm ci && npm run build` — Django serves `web/dist` at **http://127.0.0.1:8000/** (see `clawagora_server/urls.py`). For Vite HMR during UI work: `npm run dev` in `web/` (proxies `/api` to port 8000).

**Concept closure (task → bridge)**

- Create tasks with optional `metadata.clawagora_context`: `session_id`, `correlation_id`, `memory_refs` (string array) — validated on create and after **amend** merge.
- OpenClaw **delegate** POST body is `clawagora.openclaw.delegate.v1`: includes full `metadata` and, when context is set, a top-level **`context`** mirror so bridges do not have to dig for correlation IDs.
- `PATCH .../amend/` **merges** `metadata` into the existing task (shallow merge; **`clawagora_context`** and **`openclaw`** are merged one level deep), then reapplies size limits and `clawagora_context` validation.

**Control plane map (UI ↔ concern)** — one screen, separated duties (intake vs review vs legislation vs ops):

| UI area | Primary concern | Main API / artifact |
|--------|-------------------|---------------------|
| **Start a run** (left) | Submit work, optional async / delegate / `clawagora_context` | `POST /api/v1/tasks/` |
| **Result** (left) | Timeline, receipt, stored context, OpenClaw phase | `GET …/timeline/`, `…/receipt/`, task `metadata` |
| **Tasks tab** (right) | History queue, filters, click to inspect | `GET /api/v1/tasks/` |
| **Policies tab** (right) | Policy drafts: create, activate, deactivate all | `GET|POST /api/v1/policies/`, `…/activate/`, `…/deactivate/` |
| **Governance tab** (right) | Strictness level (minimal/balanced/strict), daily budget, alerts | `GET|POST /api/v1/governance/profiles/`, `/governance/dashboard/` |

## Docker quick start

This repository now includes a root `Dockerfile` and compose services for:

- `app` (Django API)
- `worker` (RQ worker)
- `bridge` (OpenClaw mock bridge for delegate/callback validation)
- `postgres` and `redis`

Run:

```bash
docker compose up --build
```

API will be available at `http://localhost:8000`.

To embed the commit in `GET /api/v1/health/` as `git_sha`, rebuild with:

```bash
export GIT_SHA="$(git rev-parse HEAD)"
docker compose build
```

Compose passes `GIT_SHA` into the image build (`docker-compose.yml` `build.args`).

### Gemma 4 quick start (Ollama / OpenAI-compatible)

```bash
# Option A: Ollama native endpoint
export CLAWAGORA_MODEL_PROVIDER=ollama
export CLAWAGORA_MODEL_URL=http://127.0.0.1:11434
export CLAWAGORA_MODEL_NAME=gemma4:latest

# Option B: OpenAI-compatible endpoint (Ollama / vLLM / LM Studio / gateway)
# export CLAWAGORA_MODEL_PROVIDER=openai_compat
# export CLAWAGORA_MODEL_URL=http://127.0.0.1:11434
# export CLAWAGORA_MODEL_NAME=gemma4:latest
# export CLAWAGORA_MODEL_API_KEY=optional
```

`CLAWAGORA_MODEL_NAME` is fully configurable. If your environment uses a different tag
(`gemma3:27b`, `gemma4:9b`, hosted model IDs, etc.), set it directly without code changes.

HTTP API (JSON):

- `GET /api/v1/health/` — liveness: database check; includes **`version`** (from `clawagora.version`) and optional **`git_sha`** (from `GIT_SHA` or `SOURCE_COMMIT` env); includes cache summary (`cache.backend`, `cache.shared`, `cache.status`), plus **Redis + queue metrics** when `django_rq` is installed (`queued_jobs`, `started_jobs`, `deferred_jobs`)
- `GET /api/v1/tasks/` — list tasks (`?status=` includes `needs_revision`; `?risk_tier=low|medium|high`; `?q=` substring on `input_text`; `?judicial_queue=1` for `pending_approval`; `?limit=`, `?offset=`); returns `count`, `limit`, `offset`, `results[]`
- `POST /api/v1/tasks/` — create and execute a task (body: `{ "input_text": "...", "metadata": {} }`). Optional `metadata.clawagora_context`: `{ "session_id"?, "correlation_id"?, "memory_refs"? }` (string array, bounded) for cross-run correlation / external memory handles; duplicated on delegate POST as `context`. Returns `201` (sync completed), `202` (async queued **or** paused for human approval), with `Location` header pointing at the task resource.
- `POST /api/v1/tasks/<uuid>/retry/` — retry a **failed** or **`needs_revision`** (judicial reject) task
- `PATCH /api/v1/tasks/<uuid>/amend/` — edit `input_text` / `metadata` on **`failed`** or **`needs_revision`** tasks before retry; `metadata` is **merged** into the stored task (nested merge for `clawagora_context` and `openclaw`)
- `POST /api/v1/tasks/<uuid>/cancel/` — cancel a task in `received` or `queued` state before execution starts
- `POST /api/v1/tasks/<uuid>/inject/` — inject operator guidance into a running task (appends a `guidance` event to the timeline)
- `POST /api/v1/tasks/<uuid>/replay/` — forensic replay of a completed task; body: `{ "mode": "events" | "decisions" }`
- `GET /api/v1/tasks/<uuid>/`
- `GET /api/v1/tasks/<uuid>/timeline/`
- `GET /api/v1/tasks/<uuid>/receipt/`
- `GET /api/v1/tasks/<uuid>/governance/` — governance loop snapshot (narrative stage, role weights, efficiency signals, recent governance timeline)
- `POST /api/v1/tasks/<uuid>/approve/` — operator approval for a `pending_approval` task; body: `{ "voter_id": "...", "rationale": "..." }`
- `POST /api/v1/tasks/<uuid>/reject/` — operator rejection for a `pending_approval` task; on quorum reject the task becomes **`needs_revision`** (returned for revision), not terminal `failed`; body: `{ "voter_id": "...", "rationale": "..." }`
- `POST /api/v1/tasks/<uuid>/vote/` — cast a named quorum vote (for multi-reviewer approval); body: `{ "voter_id": "...", "decision": "approve" | "reject", "rationale": "..." }`
- `GET /api/v1/tasks/<uuid>/votes/` — list all cast votes for an approval request
- `GET|POST /api/v1/policies/` — list or create policy drafts; body on POST: `{ "name": "...", "content": { "allowed_executors": [], "deny_patterns": [] } }`
- `GET|PUT|DELETE /api/v1/policies/<uuid>/` — read, update, or delete a policy draft by ID
- `POST /api/v1/policies/<uuid>/activate/` — activate a policy draft (deactivates any previously active draft); invalidates the active-policy cache
- `POST /api/v1/policies/deactivate/` — deactivate all policy drafts (no active policy); invalidates the active-policy cache
- `GET /api/v1/policies/activation-log/` — legislative audit log of policy activations / deactivate-all (`?limit=`)
- `GET|POST /api/v1/capabilities/` — list or register **capability bundle** metadata (skill/doc URL inventory); `GET|PATCH|DELETE /api/v1/capabilities/<uuid>/`
- `GET /api/v1/integrations/openclaw/status/` — optional OpenClaw gateway health probe (see `CLAWAGORA_OPENCLAW_*`); response always includes a sanitized `delegate` object (bridge URL, callback URL, agent defaults, webhook configured flag — never the secret)
- `POST /api/v1/integrations/openclaw/callback/` — signed callback from an external OpenClaw **bridge** (HMAC `X-ClawAgora-Signature`); completes or fails a task in `awaiting_callback`. Optional top-level **`artifacts`** array (`clawagora.openclaw.callback.v1`): each item is `{ "role": string, "content" or "text": string, optional "agent_id", optional "meta": { ... } }` for multi-agent proposal/critique/review lanes. Normalized artifacts are stored on `metadata.openclaw.artifacts` and on `receipt.body.openclaw_artifacts`; timeline `openclaw_completed` includes counts/roles.
- `POST /api/v1/tasks/<uuid>/integrations/openclaw/delegate/` — set `metadata.openclaw.delegate` and run (optional body `agents[]`); requires `CLAWAGORA_OPENCLAW_DELEGATE_ENABLED` and delegate URL for execution. Delegate payloads include **`callback_schema`: `clawagora.openclaw.callback.v1`** so bridges know they may attach `artifacts`.

Full operator spec (three-powers rollout): **docs/GOVERNANCE_THREE_PHASES.md**.
- `POST /api/v1/governance/feedback/` — apply manual accountability feedback to a task (`task_id`, `entries[]`, optional `source`); updates metadata and appends a dedicated `governance` timeline event
- `GET /api/v1/governance/leaderboard/` — cross-task role leaderboard with efficiency metrics and recommended next-round weights (`?profile=constitutional_western&limit=20`)
- `GET /api/v1/governance/dashboard/` — operations panel payload: daily budget usage/remaining, top roles, and governance alerts
- `GET /api/v1/governance/summary/` — read-only aggregate: active policy, capability integrity vs `CLAWAGORA_CAPABILITY_REQUIRE_*`, prompt registry + circuit metrics, OpenClaw delegate hints (`schema: clawagora.governance.summary.v1`)
- `GET|POST /api/v1/governance/profiles/` — governance level profile cards and one-click default level selection for new tasks
- `POST /api/v1/governance/apply-recommendations/` — persist leaderboard recommendations as profile baseline weights (`dry_run=true` previews diff only, `governance_level=minimal|balanced|strict` controls adaptation speed); future tasks in that profile inherit these baseline weights automatically
- `POST /api/v1/governance/rollback/` — rollback governance profile baseline weights to the previous revision
- `GET /api/v1/governance/leaderboard/history/` — revision history with why/evidence/impact records
- `GET /api/v1/governance/budget/forecast/` — daily budget forecast and estimated exhaustion time
- `GET|POST /api/v1/governance/alerts/subscriptions/` — alert subscription registry (`webhook`/`slack`/`feishu`)
- `GET /api/v1/governance/dead-letters/` — inspect failed deliveries with replay status
- `POST /api/v1/governance/dead-letters/replay/` — replay unresolved dead letters in batch
  (`limit`, optional `profile`, optional `event_type`, optional `dry_run`)

Headers:

- `X-ClawAgora-Execution` — `sync` (default) or `async`; when `async`, the task is stored as `queued` and processed by an RQ worker (requires `pip install clawagora[async]` and Redis). Overrides `CLAWAGORA_EXECUTION_MODE` for that request.
- `Idempotency-Key` — optional; duplicate POSTs with the same key return the existing task (`200`) without starting a second execution
- `X-API-Key` — required when `CLAWAGORA_API_KEY` is set in the environment
- `X-Submitted-By` — optional; submitter identity string stored on the task and used to enforce proposer ≠ approver separation (a voter whose `voter_id` matches `submitted_by` cannot approve their own task)
- `X-Request-ID` — optional; echoed on the response for correlation

Error handling contract:

- API exceptions are returned as `{status, code, body}` (enveloped format).
- Error code definitions are centralized in `apps/server/orchestration/error_codes.py`.
- Persisted task failure codes (`Task.error_code`) use the same centralized registry to keep API and storage semantics aligned.

Environment (async):

| Variable | Purpose |
|----------|---------|
| `CLAWAGORA_EXECUTION_MODE` | Default `sync`; set to `async` to prefer async when the header is omitted |
| `REDIS_URL` | Broker URL for django-rq (default `redis://127.0.0.1:6379/0`) |
| `RQ_DEFAULT_TIMEOUT` | Job timeout seconds (default `360`) |

```bash
docker compose up -d redis
export REDIS_URL=redis://127.0.0.1:6379/0
bash scripts/worker.sh
```

Environment (selected):

| Variable | Purpose |
|----------|---------|
| `DJANGO_DEBUG` | `1`/`0` (production must use `0` and a real `DJANGO_SECRET_KEY`) |
| `CLAWAGORA_API_KEY` | If set, gates all API routes with matching `X-API-Key` |
| `CLAWAGORA_THROTTLE_RATE` | Default `120/minute` (anonymous DRF throttle) |
| `CLAWAGORA_MAX_INPUT_CHARS` | Max `input_text` length (default `256000`) |
| `CLAWAGORA_EXPOSE_ERROR_DETAIL` | Set `1` to expose `error_detail` JSON in task responses when not in `DEBUG` |
| `CLAWAGORA_GOVERNANCE_KEY` | Optional dedicated key for governance write endpoints (`X-Governance-Key`); falls back to policy key when unset |
| `CLAWAGORA_GOVERNANCE_DAILY_BUDGET_MINIMAL_BPS` | Per-role max absolute baseline change per day in minimal mode (default `6000` = `0.60`) |
| `CLAWAGORA_GOVERNANCE_DAILY_BUDGET_BALANCED_BPS` | Per-role max absolute baseline change per day in balanced mode (default `3500` = `0.35`) |
| `CLAWAGORA_GOVERNANCE_DAILY_BUDGET_STRICT_BPS` | Per-role max absolute baseline change per day in strict mode (default `1800` = `0.18`) |
| `CLAWAGORA_GOVERNANCE_ALERT_MAX_RETRIES` | Max alert delivery retries before dead-letter (default `3`) |
| `CLAWAGORA_GOVERNANCE_ALERT_BUDGET_NEAR_EXHAUSTED_BPS` | Budget usage ratio threshold for `budget_near_exhausted` alerts (default `9000` = `0.90`) |
| `CLAWAGORA_GOVERNANCE_ALERT_LOW_EFFICIENCY_BPS` | Efficiency threshold for `low_efficiency` alerts (default `4500` = `0.45`) |
| `CLAWAGORA_GOVERNANCE_SNAPSHOT_TTL_SECONDS` | Snapshot freshness window for O(1) governance reads (default `20`) |
| `CLAWAGORA_GOVERNANCE_SIGNING_KEY` | HMAC key for outgoing alert signatures (`X-ClawAgora-Signature`) |
| `CLAWAGORA_GOVERNANCE_LB_DELTA_GAIN_BPS` | Leaderboard recommended-weight delta coefficient (default `9000` = `0.90`) |
| `CLAWAGORA_GOVERNANCE_LB_SUCCESS_GAIN_BPS` | Leaderboard recommended-weight success coefficient (default `2000` = `0.20`) |
| `CLAWAGORA_GOVERNANCE_LB_INCIDENT_PENALTY_BPS` | Leaderboard recommended-weight incident penalty coefficient (default `1200` = `0.12`) |
| `CLAWAGORA_GOVERNANCE_LB_EFF_SUCCESS_BPS` | Efficiency-score success contribution coefficient (default `7000` = `0.70`) |
| `CLAWAGORA_GOVERNANCE_LB_EFF_INCIDENT_BPS` | Efficiency-score incident contribution coefficient (default `3000` = `0.30`) |
| `CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MIN_BPS` | Recommended-weight lower bound (default `4000` = `0.40`) |
| `CLAWAGORA_GOVERNANCE_LB_RECOMMENDED_MAX_BPS` | Recommended-weight upper bound (default `22000` = `2.20`) |
| `CLAWAGORA_GOVERNANCE_LEADERBOARD_SCAN_LIMIT` | Max tasks scanned per governance leaderboard/dashboard refresh (default `500`) |
| `CLAWAGORA_GOVERNANCE_ALERT_SCAN_LIMIT` | Max ranked roles scanned per alert delivery loop (default `200`) |
| `CLAWAGORA_GOVERNANCE_RESPONSE_CACHE_TTL_SECONDS` | In-process response cache TTL for governance read endpoints (default `20`) |
| `CLAWAGORA_GOVERNANCE_LIST_DEFAULT_LIMIT` | Default list limit for governance list endpoints (default `20`) |
| `CLAWAGORA_GOVERNANCE_LIST_MAX_LIMIT` | Max list limit for governance list endpoints (default `100`) |
| `CLAWAGORA_GOVERNANCE_DEAD_LETTER_DEFAULT_LIMIT` | Default dead-letter list/replay limit (default `50`) |
| `CLAWAGORA_GOVERNANCE_DEAD_LETTER_MAX_LIMIT` | Max dead-letter list limit (default `200`) |
| `CLAWAGORA_GOVERNANCE_REPLAY_PREVIEW_MAX_ITEMS` | Max preview items returned in dead-letter replay result (default `100`) |
| `CLAWAGORA_TASK_LIST_DEFAULT_LIMIT` | Default list limit for `GET /api/v1/tasks/` (default `20`) |
| `CLAWAGORA_TASK_LIST_MAX_LIMIT` | Max list limit for `GET /api/v1/tasks/` (default `200`) |
| `LOG_LEVEL` | Python root log level (default `INFO`) |
| `LOG_FORMAT` | `text` (default) or `json` for machine-parseable logs (`request_id`, `task_id` when bound) |
| `CLAWAGORA_DEFAULT_GOVERNANCE_PROFILE` | Default governance profile name used when no `profile` query parameter is supplied (default `constitutional_western`) |
| `CLAWAGORA_EXECUTOR_POOL_SIZE` | Max worker threads for the `TaskPipeline` executor pool (default `8`) |
| `CLAWAGORA_HEAL_ENABLED` | `1`/`0` — if `0`, `heal_stale_tasks` / `clawagora_heal` are no-ops |
| `CLAWAGORA_STALE_RUNNING_SECONDS` | RUNNING tasks with no update longer than this are marked **failed** (stale worker/API) — default `3600` |
| `CLAWAGORA_STALE_QUEUED_SECONDS` | QUEUED tasks older than this are healed — default `1800`; default action **failed** unless requeue is enabled |
| `CLAWAGORA_HEAL_REQUEUE_STALE_QUEUED` | Set `1` to try re-enqueuing stale QUEUED tasks when RQ is available; otherwise they become **failed** |
| `CLAWAGORA_MODEL_TEMPERATURE` | Default model temperature for LLM calls (default `0.0`) |
| `CLAWAGORA_MODEL_MAX_TOKENS` | Default max output tokens per model call (default `512`) |
| `CLAWAGORA_MODEL_COST_INPUT_PER_MTOK_USD` | Input token price (USD per 1M tokens) for cost estimation logs (default `0`) |
| `CLAWAGORA_MODEL_COST_OUTPUT_PER_MTOK_USD` | Output token price (USD per 1M tokens) for cost estimation logs (default `0`) |
| `CLAWAGORA_MODEL_TOKEN_CHARS_ESTIMATE` | Characters-per-token estimator used for usage/cost approximation (default `4`) |
| `CLAWAGORA_RISK_HIGH_PATTERNS` | Comma-separated regex patterns for `HIGH` risk tier; defaults include `drop\\s+table`, `payment`, `api[-_]?key` |
| `CLAWAGORA_RISK_MEDIUM_PATTERNS` | Comma-separated regex patterns for `MEDIUM` risk tier (deploy/update/database lifecycle actions by default) |
| `CLAWAGORA_OPENCLAW_ENABLED` | `1` enables `GET /api/v1/integrations/openclaw/status/` network probe |
| `CLAWAGORA_OPENCLAW_GATEWAY_URL` | OpenClaw (or compatible) gateway base URL for the probe |
| `CLAWAGORA_OPENCLAW_API_KEY` | Optional bearer token for the gateway probe |
| `CLAWAGORA_OPENCLAW_STATUS_TIMEOUT_SEC` | Probe timeout in seconds (default `3`) |
| `CLAWAGORA_OPENCLAW_DELEGATE_ENABLED` | `1` allows `metadata.openclaw.delegate=true` to POST to an external bridge instead of local kernel |
| `CLAWAGORA_OPENCLAW_DELEGATE_URL` | Bridge URL for delegate JSON (`clawagora.openclaw.delegate.v1`; body includes `metadata`, optional top-level `context` when `metadata.clawagora_context` is set). |
| `CLAWAGORA_OPENCLAW_DELEGATE_TIMEOUT_SEC` | Delegate POST timeout (default `60`) |
| `CLAWAGORA_PUBLIC_BASE_URL` | Public API origin (no trailing slash) for `callback_url` in delegate payloads |
| `CLAWAGORA_OPENCLAW_WEBHOOK_SECRET` | HMAC secret for `X-ClawAgora-Signature` on `POST /api/v1/integrations/openclaw/callback/` |
| `CLAWAGORA_OPENCLAW_AGENT_CONFIG_JSON` | JSON: `default_agents` / `by_risk` merged with per-task `metadata.openclaw.agents` |
| `CLAWAGORA_OPENCLAW_CALLBACK_REQUIRE_GUARD` | `1` requires anti-replay headers on callback (`X-ClawAgora-Timestamp`, `X-ClawAgora-Nonce`) |
| `CLAWAGORA_OPENCLAW_CALLBACK_MAX_SKEW_SEC` | Allowed callback timestamp clock skew in seconds (default `300`) |
| `CLAWAGORA_OPENCLAW_CALLBACK_NONCE_TTL_SEC` | Nonce replay-lock TTL in seconds (default `900`) |
| `CLAWAGORA_CACHE_URL` | Optional shared cache URL (recommended: Redis). Set this in multi-instance deployments so callback replay guard is globally enforced. |
| `CLAWAGORA_CAPABILITY_REQUIRE_SHA256` | `1` requires active capability bundles to set `source_sha256` (64 hex) — reduces knowledge drift |
| `CLAWAGORA_CAPABILITY_REQUIRE_SOURCE_URL` | `1` requires active bundles to set `source_url` |

When `DJANGO_DEBUG=0`, set `CORS_ALLOWED_ORIGINS` for browser clients and optionally `SECURE_SSL_REDIRECT=1` behind TLS termination.

Governance metadata keys:

- `governance_profile` — e.g. `constitutional_western`
- `governance_level` — `minimal`, `balanced` (default), or `strict` (stronger anti-drift smoothing)

Prompt management:

- Prompt templates are centrally managed in `src/clawagora/prompts.py` (registry pattern).
- Prompt versioning uses `prompt_key + version + rollout` with deterministic hash rollout by `request_id`.
- `ClassifyService` and `Synthesizer` resolve prompts by key/version instead of embedding inline constants.
- Shared knowledge can be registered as capability bundles via `GET|POST /api/v1/capabilities/` (with `source_url`, `source_sha256`, and `bound_executors`) so teams reuse the same validated knowledge sources.
- Governance policy can enforce how prompts/knowledge are used at execution time (allowlists/deny patterns and approval flow), giving a single control plane instead of per-agent prompt drift.
- Automated integrity scan (optional): `python apps/server/manage.py clawagora_capability_integrity` lists active bundles missing required pins when `CLAWAGORA_CAPABILITY_REQUIRE_*` is enabled; use `--deactivate` to soft-disable offenders.

Cost management:

- Providers emit usage logs with estimated `input_tokens`, `output_tokens`, and `est_cost_usd`.
- Estimation uses configurable model cost policy values from `CLAWAGORA_MODEL_COST_*`.
- Provider usage logs include `prompt_key` and `prompt_version` for fast online prompt-effect traceability.

### Governance worker (alerts + snapshots)

```bash
export PYTHONPATH="$(pwd)/src:$(pwd)/apps/server"
export DJANGO_SETTINGS_MODULE=clawagora_server.settings
python apps/server/manage.py clawagora_governance_worker --json
# only snapshots: python ... clawagora_governance_worker --refresh-snapshots
# only alert delivery: python ... clawagora_governance_worker --deliver-alerts
# replay dead letters: python ... clawagora_governance_worker --replay-dead-letters --limit 50
# scoped replay: python ... clawagora_governance_worker --replay-dead-letters --profile constitutional_western --event-type low_efficiency
# safe preview only: python ... clawagora_governance_worker --replay-dead-letters --dry-run --limit 50
```

### Logging and stale-task healing

- Prefer `LOG_FORMAT=json` behind a log collector; HTTP binds `request_id` (from `X-Request-ID` or generated); worker jobs bind `task_id`.
- Run the management command on a schedule (cron, systemd timer, or Kubernetes `CronJob`) so stuck `running` / `queued` rows recover without manual DB edits:

```bash
export PYTHONPATH="$(pwd)/src:$(pwd)/apps/server"
export DJANGO_SETTINGS_MODULE=clawagora_server.settings
python apps/server/manage.py clawagora_heal
# Dry-run (no DB updates): python apps/server/manage.py clawagora_heal --dry-run
# Machine output: python apps/server/manage.py clawagora_heal --json
```

Example Kubernetes `CronJob` (adjust image/command to your deployment):

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: clawagora-heal
spec:
  schedule: "*/10 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: heal
              image: your-clawagora-image:tag
              command: ["python", "manage.py", "clawagora_heal"]
```

## Run UI (development)

```bash
cd web
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

## Build UI (production bundle)

```bash
cd web
npm run build
```

When `web/dist` exists, the Django app serves the UI and JSON API from the same origin.

## Tests

```bash
export PYTHONPATH="$(pwd)/src:$(pwd)/apps/server"
pytest -q
```

## Domain packs

Task intent is classified and routed to a domain pack that selects the executor sequence:

| Intent label | Pack | Executor |
|---|---|---|
| `engineering` | `coding` | `executor_coding` — code analysis (tokens, complexity, keywords, fingerprint) |
| `research` | `research` | `executor_research` — keyword extraction and structured research summary |
| `support` | `support` | `executor_support` — safe ticket formatting with priority estimation |
| any other / unmatched | default | `executor_transform` → `executor_echo` |

Register custom domain packs at runtime without modifying library source:

```python
from clawagora.packs import PackRegistry

registry = PackRegistry()
registry.register(
    "image_gen",
    executors=["executor_image_gen"],
    validators=["schema", "safety"],  # optional; defaults to schema + policy + safety
)
```

## Runtime signals

Every completed task receipt includes three automatic fields:

| Receipt key | Type | Description |
|---|---|---|
| `trust_score` | `{ value: float, reasons: [] }` | Derived from classification confidence and validation pass/fail; 0.0–1.0 |
| `optimization` | `{ task_id, items: [] }` | Actionable recommendations: `LOW_CLASSIFICATION_CONFIDENCE`, `HIGH_STEP_COUNT`, `VALIDATION_WARNINGS` |
| `rollback_plan` | `{ task_id, steps: [] }` | Checkpoint map from completed execution artifacts for compensating-action derivation |

`DynamicRouter` provides weighted executor selection seeded by `task_id + step_id` for deterministic replay:

```python
from clawagora.runtime import DynamicRouter, RoutingTarget, TrustScore

router = DynamicRouter(
    targets=[
        RoutingTarget(executor_id="executor_coding",   weight=1.2),
        RoutingTarget(executor_id="executor_transform", weight=0.8),
    ]
)
selected = router.select("task-uuid-step-1")
# Trust-adjusted selection (boosts high-weight targets at high trust):
selected = router.select("task-uuid-step-1", trust=TrustScore(value=0.9))
```

## Documentation

See `docs/ARCHITECTURE.md` for the product and technical roadmap.
For OpenClaw end-to-end verification and no-blind-spot checks, see `docs/OPENCLAW_E2E_RUNBOOK.md`.

Contributing and security: [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md).

## License

MIT

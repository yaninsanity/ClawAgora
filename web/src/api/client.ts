export type TaskStatus =
  | "received"
  | "queued"
  | "running"
  | "pending_approval"
  | "needs_revision"
  | "completed"
  | "failed"
  | "cancelled";

export type ReceiptRecord = {
  body: Record<string, unknown>;
  body_hash: string;
  created_at: string;
};

export type ApprovalVote = {
  id: string;
  voter_id: string;
  decision: "approve" | "reject";
  rationale: string;
  created_at: string;
};

export type ApprovalRequest = {
  id: string;
  ticket_id: string;
  risk_tier: string;
  summary: string;
  status: string;
  quorum: number;
  approve_count: number;
  reject_count: number;
  threshold: number;
  decision_note: string;
  created_at: string;
  decided_at: string | null;
  votes: ApprovalVote[];
};

export type TaskRecord = {
  id: string;
  external_ref: string;
  status: TaskStatus;
  input_text: string;
  submitted_by: string;
  metadata: Record<string, unknown>;
  risk_tier: string;
  classification: {
    label: string;
    confidence: number;
    tags: string[];
  } | null;
  plan: unknown;
  validation_reports: unknown;
  error_code: string;
  error_detail: Record<string, unknown> | null;
  run_attempt: number;
  receipt: ReceiptRecord | null;
  approval_request: ApprovalRequest | null;
  created_at: string;
  updated_at: string;
};

export type TaskListItem = {
  id: string;
  status: TaskStatus;
  input_text: string | undefined;
  risk_tier: string;
  error_code: string;
  run_attempt: number;
  created_at: string;
  updated_at: string;
};

export type TimelineEvent = {
  sequence: number;
  phase: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ReplayRecord = {
  sequence: number;
  phase: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type PolicyDraft = {
  id: string;
  name: string;
  content: Record<string, unknown>;
  is_active: boolean;
  updated_at: string;
};

export type GovernanceLevelCard = {
  level: "minimal" | "balanced" | "strict";
  latency_estimate: string;
  risk_control: string;
  cost_estimate: string;
  selected: boolean;
};

export type GovernanceProfiles = {
  profile: string;
  selected_level: string;
  cards: GovernanceLevelCard[];
};

export type GovernanceDashboard = {
  profile: string;
  governance_level: string;
  daily_budget: number;
  daily_budget_used: Record<string, number>;
  daily_budget_remaining: Record<string, number>;
  leaderboard_top: unknown[];
  alerts: unknown[];
  tasks_scanned?: number;
  narrative?: string;
};

export type GovernanceSummary = {
  schema: string;
  version: string;
  policy: {
    has_active_policy: boolean;
    active_policy_id: string | null;
    active_policy_name: string | null;
    active_policy_updated_at: string | null;
    draft_count: number;
  };
  capabilities: {
    require_sha256: boolean;
    require_source_url: boolean;
    active_bundle_count: number;
    total_bundle_count: number;
    offender_count: number;
    offenders: Array<{ id: string; slug: string; reasons: string[] }>;
  };
  prompts: {
    circuit_breaker: {
      enabled: boolean;
      min_samples: number;
      error_rate_max: number;
      avg_cost_usd_max: number;
      metrics_ttl_seconds: number;
      cooldown_seconds: number;
      fallback_version_default: string;
    };
    registry_keys: Array<{
      prompt_key: string;
      circuit_forced_version: string | null;
      versions: Array<{
        version: string;
        rollout: number;
        metrics: Record<string, unknown> | null;
      }>;
    }>;
  };
  integrations: {
    openclaw_delegate: {
      enabled?: boolean;
      url_configured?: boolean;
      callback_url?: string | null;
      callback_guard_cache_backend?: string;
      knowledge?: {
        capability_require_sha256: boolean;
        capability_require_source_url: boolean;
      };
    };
  };
};


export type ApiErrorPayload = {
  status: number;
  code: string;
  body: unknown;
};

const base = () => (import.meta.env.VITE_API_BASE as string | undefined) || "";

function parseError(res: Response, text: string): Error {
  try {
    const j = JSON.parse(text) as ApiErrorPayload;
    if (typeof j.status === "number" && j.body !== undefined) {
      return new Error(`HTTP ${res.status}: ${JSON.stringify(j.body)}`);
    }
  } catch {
    /* ignore */
  }
  return new Error(`HTTP ${res.status}: ${text}`);
}

function assertJsonArray(data: unknown, apiLabel: string): unknown[] {
  if (!Array.isArray(data)) {
    throw new Error(`${apiLabel}: response must be a JSON array.`);
  }
  return data;
}

function assertTaskListEnvelope(
  data: unknown,
): { results: TaskListItem[]; count: number } {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("Task list: response must be a JSON object.");
  }
  const o = data as Record<string, unknown>;
  if (!Array.isArray(o.results)) {
    throw new Error("Task list: missing results array.");
  }
  const count =
    typeof o.count === "number" && Number.isFinite(o.count) ? o.count : 0;
  return { results: o.results as TaskListItem[], count };
}

export async function fetchTask(taskId: string): Promise<TaskRecord> {
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/`);
  const text = await res.text();
  if (!res.ok) {
    throw parseError(res, text);
  }
  return JSON.parse(text) as TaskRecord;
}

export async function listTasks(params?: {
  status?: string;
  risk_tier?: string;
  q?: string;
  judicial_queue?: boolean;
  limit?: number;
  offset?: number;
}): Promise<{ results: TaskListItem[]; count: number }> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.risk_tier) q.set("risk_tier", params.risk_tier);
  if (params?.q) q.set("q", params.q);
  if (params?.judicial_queue) q.set("judicial_queue", "1");
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.size > 0 ? "?" + q.toString() : "";
  const res = await fetch(base() + "/api/v1/tasks/" + qs);
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return assertTaskListEnvelope(JSON.parse(text) as unknown);
}

export async function createTask(
  input: string,
  options?: {
    idempotencyKey?: string;
    execution?: "sync" | "async";
    metadata?: Record<string, unknown>;
  }
): Promise<{ task: TaskRecord; httpStatus: number }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options?.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }
  if (options?.execution) {
    headers["X-ClawAgora-Execution"] = options.execution;
  }
  const res = await fetch(base() + "/api/v1/tasks/", {
    method: "POST",
    headers,
    body: JSON.stringify({
      input_text: input,
      metadata: options?.metadata && Object.keys(options.metadata).length > 0 ? options.metadata : {},
    }),
  });
  const text = await res.text();
  if (!res.ok) {
    throw parseError(res, text);
  }
  return { task: JSON.parse(text) as TaskRecord, httpStatus: res.status };
}

export async function amendTask(
  taskId: string,
  body: { input_text?: string; metadata?: Record<string, unknown> }
): Promise<TaskRecord> {
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/amend/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as TaskRecord;
}

export async function retryTask(taskId: string, execution?: "sync" | "async"): Promise<TaskRecord> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (execution) {
    headers["X-ClawAgora-Execution"] = execution;
  }
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/retry/`, {
    method: "POST",
    headers,
    body: "{}",
  });
  const text = await res.text();
  if (!res.ok) {
    throw parseError(res, text);
  }
  return JSON.parse(text) as TaskRecord;
}

export async function cancelTask(taskId: string): Promise<TaskRecord> {
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/cancel/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as TaskRecord;
}

export async function fetchTimeline(taskId: string): Promise<TimelineEvent[]> {
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/timeline/`);
  const text = await res.text();
  if (!res.ok) {
    throw parseError(res, text);
  }
  const data = JSON.parse(text) as unknown;
  if (!Array.isArray(data)) {
    throw new Error("Timeline API returned a non-array body.");
  }
  return data as TimelineEvent[];
}

export async function fetchReplay(
  taskId: string,
  mode: "events" | "decisions" = "events"
): Promise<ReplayRecord[]> {
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/replay/?mode=${mode}`);
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  const data = JSON.parse(text) as { mode: string; task_id: string; records: ReplayRecord[] };
  return data.records ?? [];
}

export async function activatePolicy(policyId: string): Promise<PolicyDraft> {
  const res = await fetch(base() + `/api/v1/policies/${policyId}/activate/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as PolicyDraft;
}

export async function deactivateAllPolicies(): Promise<void> {
  const res = await fetch(base() + "/api/v1/policies/deactivate/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!res.ok) {
    const text = await res.text();
    throw parseError(res, text);
  }
}

export async function fetchGovernanceProfiles(): Promise<GovernanceProfiles> {
  const res = await fetch(base() + "/api/v1/governance/profiles/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as GovernanceProfiles;
}

export async function setGovernanceLevel(
  level: "minimal" | "balanced" | "strict"
): Promise<{ profile: string; selected_level: string }> {
  const res = await fetch(base() + "/api/v1/governance/profiles/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as { profile: string; selected_level: string };
}

export async function fetchGovernanceDashboard(): Promise<GovernanceDashboard> {
  const res = await fetch(base() + "/api/v1/governance/dashboard/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as GovernanceDashboard;
}

export async function fetchGovernanceSummary(): Promise<GovernanceSummary> {
  const res = await fetch(base() + "/api/v1/governance/summary/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as GovernanceSummary;
}

export type GovernanceExecutorOption = { id: string; label: string };

export type GovernanceExecutorsPayload = {
  schema: string;
  executors: GovernanceExecutorOption[];
};

/** Legislative allowlist ids — matches the server TaskPipeline registry. */
export async function fetchGovernanceExecutors(): Promise<GovernanceExecutorsPayload> {
  const res = await fetch(base() + "/api/v1/governance/executors/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as GovernanceExecutorsPayload;
}

export async function listPolicies(): Promise<PolicyDraft[]> {
  const res = await fetch(base() + "/api/v1/policies/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  const data = JSON.parse(text) as unknown;
  return assertJsonArray(data, "Policies list") as PolicyDraft[];
}

export async function createPolicy(
  name: string,
  content: Record<string, unknown>
): Promise<PolicyDraft> {
  const res = await fetch(base() + "/api/v1/policies/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, content }),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as PolicyDraft;
}

export async function deletePolicy(policyId: string): Promise<void> {
  const res = await fetch(base() + `/api/v1/policies/${policyId}/`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const text = await res.text();
    throw parseError(res, text);
  }
}

export async function updatePolicy(
  policyId: string,
  body: { name?: string; content?: Record<string, unknown> },
): Promise<PolicyDraft> {
  const res = await fetch(base() + `/api/v1/policies/${policyId}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as PolicyDraft;
}

function isAwaitingOpenClawCallback(t: TaskRecord): boolean {
  const oc = t.metadata?.openclaw;
  if (oc && typeof oc === "object" && oc !== null && "phase" in oc) {
    return (oc as { phase?: string }).phase === "awaiting_callback";
  }
  return false;
}

export async function waitForTerminal(
  taskId: string,
  pollMs = 1500,
  maxAttempts = 80
): Promise<TaskRecord> {
  let t = await fetchTask(taskId);
  let n = 0;
  while (
    (t.status === "queued" || t.status === "running") &&
    !(t.status === "running" && isAwaitingOpenClawCallback(t)) &&
    n < maxAttempts
  ) {
    await new Promise((r) => setTimeout(r, pollMs));
    t = await fetchTask(taskId);
    n += 1;
  }
  return t;
}

export async function approveTask(
  taskId: string,
  voterId?: string,
  note?: string
): Promise<TaskRecord> {
  const body: Record<string, string> = {};
  if (voterId) body.voter_id = voterId;
  if (note) body.note = note;
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/approve/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as TaskRecord;
}

export async function rejectTask(
  taskId: string,
  voterId?: string,
  note?: string
): Promise<TaskRecord> {
  const body: Record<string, string> = {};
  if (voterId) body.voter_id = voterId;
  if (note) body.note = note;
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/reject/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as TaskRecord;
}

export async function castVote(
  taskId: string,
  voterId: string,
  decision: "approve" | "reject",
  rationale?: string
): Promise<TaskRecord> {
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/vote/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voter_id: voterId, decision, rationale: rationale ?? "" }),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as TaskRecord;
}

export async function listVotes(taskId: string): Promise<ApprovalVote[]> {
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/votes/`);
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as ApprovalVote[];
}

export type PolicyActivationLogEntry = {
  id: string;
  action: "activate" | "deactivate_all";
  policy_draft_id: string | null;
  previous_active_id: string | null;
  created_at: string;
};

export async function fetchPolicyActivationLog(limit?: number): Promise<PolicyActivationLogEntry[]> {
  const q = limit != null ? `?limit=${limit}` : "";
  const res = await fetch(base() + "/api/v1/policies/activation-log/" + q);
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  const data = JSON.parse(text) as unknown;
  return assertJsonArray(data, "Policy activation log") as PolicyActivationLogEntry[];
}

export type OpenClawDelegateStatus = {
  enabled: boolean;
  url_configured: boolean;
  delegate_url: string;
  public_base_url: string;
  callback_url: string | null;
  webhook_secret_configured: boolean;
  delegate_timeout_sec: number;
  callback_guard_cache_backend?: "redis" | "locmem";
  knowledge?: {
    capability_require_sha256: boolean;
    capability_require_source_url: boolean;
  };
  agent_config: {
    default_agents: string[];
    by_risk_tiers: string[];
  };
};

export type OpenClawStatus = {
  enabled: boolean;
  gateway_url?: string;
  reachable?: boolean;
  http_status?: number | null;
  latency_ms?: number | null;
  detail?: string;
  body_preview?: Record<string, unknown> | null;
  delegate?: OpenClawDelegateStatus;
};

export async function triggerOpenClawDelegate(
  taskId: string,
  options?: { agents?: string[]; execution?: "sync" | "async" }
): Promise<TaskRecord> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options?.execution) {
    headers["X-ClawAgora-Execution"] = options.execution;
  }
  const body =
    options?.agents && options.agents.length > 0 ? JSON.stringify({ agents: options.agents }) : "{}";
  const res = await fetch(base() + `/api/v1/tasks/${taskId}/integrations/openclaw/delegate/`, {
    method: "POST",
    headers,
    body,
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as TaskRecord;
}

export async function fetchOpenClawStatus(): Promise<OpenClawStatus> {
  const res = await fetch(base() + "/api/v1/integrations/openclaw/status/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as OpenClawStatus;
}

export type CapabilityBundle = {
  id: string;
  name: string;
  slug: string;
  source_url: string;
  source_sha256: string;
  notes: string;
  bound_executors: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export async function listCapabilities(activeOnly?: boolean): Promise<CapabilityBundle[]> {
  const q = activeOnly ? "?active_only=1" : "";
  const res = await fetch(base() + "/api/v1/capabilities/" + q);
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as CapabilityBundle[];
}

export type ApprovalPolicyTemplateRow = {
  slug: string;
  name: string;
  quorum: number;
  description: string;
  sort_order: number;
};

export type GovernanceApprovalTemplatesPayload = {
  schema: string;
  runtime: {
    approval_gate_mode: string;
    approval_quorum: number;
    majority_threshold: number;
  };
  templates: ApprovalPolicyTemplateRow[];
  org_recommendation: Record<string, unknown> | null;
};

/** Judicial quorum presets; pass orgSlug for org-bound CLAWAGORA_APPROVAL_QUORUM recommendation. */
export async function fetchGovernanceApprovalTemplates(
  orgSlug?: string
): Promise<GovernanceApprovalTemplatesPayload> {
  const q = orgSlug ? `?org_slug=${encodeURIComponent(orgSlug)}` : "";
  const res = await fetch(base() + "/api/v1/governance/approval-templates/" + q);
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as GovernanceApprovalTemplatesPayload;
}

export type OrganizationUnitRow = {
  id: string;
  slug: string;
  name: string;
  parent_id: string | null;
  approval_template_slug: string | null;
  created_at: string;
};

export async function fetchOrganizationUnits(): Promise<OrganizationUnitRow[]> {
  const res = await fetch(base() + "/api/v1/governance/organization-units/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as OrganizationUnitRow[];
}

export async function patchOrganizationUnit(
  unitId: string,
  body: { approval_template_slug?: string | null; name?: string }
): Promise<OrganizationUnitRow> {
  const res = await fetch(base() + `/api/v1/governance/organization-units/${unitId}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as OrganizationUnitRow;
}

export type PolicyEvolutionProposalRow = {
  id: string;
  proposed_content: Record<string, unknown>;
  source: string;
  rationale: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string;
  derived_policy_draft_id: string | null;
};

export async function fetchPolicyProposals(): Promise<PolicyEvolutionProposalRow[]> {
  const res = await fetch(base() + "/api/v1/policies/proposals/");
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as PolicyEvolutionProposalRow[];
}

export async function resolvePolicyProposal(
  proposalId: string,
  body: { action: "accept" | "reject"; draft_name?: string; note?: string }
): Promise<PolicyEvolutionProposalRow> {
  const res = await fetch(base() + `/api/v1/policies/proposals/${proposalId}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) throw parseError(res, text);
  return JSON.parse(text) as PolicyEvolutionProposalRow;
}


import { useCallback, useEffect, useMemo, useState } from "react";
import {
  activatePolicy,
  cancelTask,
  castVote,
  createPolicy,
  createTask,
  deactivateAllPolicies,
  deletePolicy,
  fetchGovernanceDashboard,
  fetchGovernanceProfiles,
  fetchOpenClawStatus,
  fetchPolicyActivationLog,
  fetchTask,
  fetchTimeline,
  listPolicies,
  listTasks,
  retryTask,
  setGovernanceLevel,
  waitForTerminal,
  type ApprovalRequest,
  type GovernanceDashboard,
  type GovernanceProfiles,
  type OpenClawStatus,
  type PolicyActivationLogEntry,
  type PolicyDraft,
  type TaskListItem,
  type TaskRecord,
  type TimelineEvent,
} from "./api/client";
import { ReceiptPanel } from "./components/ReceiptPanel";
import { TaskTimeline } from "./components/TaskTimeline";

type RightTab = "tasks" | "policies" | "governance";
type TaskListFilter = "all" | "judicial" | "needs_revision";

export function App() {
  // ── Submit panel ──────────────────────────────────────────────────────────
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [asyncMode, setAsyncMode] = useState(false);
  const [delegateOpenClaw, setDelegateOpenClaw] = useState(false);
  const [openclawAgentsStr, setOpenclawAgentsStr] = useState("");
  const [err, setErr] = useState<string | null>(null);

  // ── Active task detail ─────────────────────────────────────────────────────
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loadingTaskId, setLoadingTaskId] = useState<string | null>(null);

  // ── Right-panel state ──────────────────────────────────────────────────────
  const [rightTab, setRightTab] = useState<RightTab>("tasks");
  const [taskList, setTaskList] = useState<TaskListItem[]>([]);
  const [policies, setPolicies] = useState<PolicyDraft[]>([]);
  const [policyName, setPolicyName] = useState("");
  const [policyContent, setPolicyContent] = useState("{}");
  const [policyErr, setPolicyErr] = useState<string | null>(null);
  const [govProfiles, setGovProfiles] = useState<GovernanceProfiles | null>(null);
  const [govDashboard, setGovDashboard] = useState<GovernanceDashboard | null>(null);
  const [govLevelBusy, setGovLevelBusy] = useState(false);
  const [openClaw, setOpenClaw] = useState<OpenClawStatus | null>(null);
  const [policyLog, setPolicyLog] = useState<PolicyActivationLogEntry[]>([]);
  const [taskListFilter, setTaskListFilter] = useState<TaskListFilter>("all");

  // ── Approval state ─────────────────────────────────────────────────────────
  const [voterId, setVoterId] = useState("operator");
  const [voteNote, setVoteNote] = useState("");

  const status = useMemo(() => task?.status ?? "idle", [task]);

  // ── Helpers ────────────────────────────────────────────────────────────────
  const refreshTaskList = useCallback(async () => {
    try {
      const params: Parameters<typeof listTasks>[0] = { limit: 30 };
      if (taskListFilter === "judicial") params.judicial_queue = true;
      else if (taskListFilter === "needs_revision") params.status = "needs_revision";
      const { results } = await listTasks(params);
      setTaskList(results);
    } catch {
      /* silent */
    }
  }, [taskListFilter]);

  const refreshPolicies = useCallback(async () => {
    try {
      setPolicies(await listPolicies());
    } catch {
      /* silent */
    }
  }, []);

  const refreshGovernance = useCallback(async () => {
    try {
      const [profiles, dashboard] = await Promise.all([
        fetchGovernanceProfiles(),
        fetchGovernanceDashboard(),
      ]);
      setGovProfiles(profiles);
      setGovDashboard(dashboard);
    } catch {
      /* silent */
    }
    try {
      setOpenClaw(await fetchOpenClawStatus());
    } catch {
      setOpenClaw(null);
    }
  }, []);

  const loadTask = useCallback(async (id: string) => {
    setLoadingTaskId(id);
    try {
      const [t, tl] = await Promise.all([
        fetchTask(id),
        fetchTimeline(id).catch(() => [] as TimelineEvent[]),
      ]);
      setTask(t);
      setEvents(tl);
    } finally {
      setLoadingTaskId(null);
    }
  }, []);

  useEffect(() => {
    void refreshPolicies();
    void refreshGovernance();
  }, [refreshPolicies, refreshGovernance]);

  useEffect(() => {
    void refreshTaskList();
  }, [taskListFilter, refreshTaskList]);

  useEffect(() => {
    if (rightTab !== "policies") return;
    void (async () => {
      try {
        setPolicyLog(await fetchPolicyActivationLog(40));
      } catch {
        setPolicyLog([]);
      }
    })();
  }, [rightTab]);

  // Auto-refresh task list while any task is in a transient state.
  useEffect(() => {
    const hasActive = taskList.some(
      (t) =>
        t.status === "queued" ||
        t.status === "running" ||
        t.status === "pending_approval" ||
        t.status === "needs_revision"
    );
    if (!hasActive) return;
    const id = setInterval(() => void refreshTaskList(), 4000);
    return () => clearInterval(id);
  }, [taskList, refreshTaskList]);

  // Auto-refresh active task detail when not already driven by waitForTerminal.
  useEffect(() => {
    if (!task || busy) return;
    if (
      task.status !== "queued" &&
      task.status !== "running" &&
      task.status !== "pending_approval" &&
      task.status !== "needs_revision"
    )
      return;
    const id = setInterval(() => void loadTask(task.id), 3000);
    return () => clearInterval(id);
  }, [task?.status, task?.id, busy, loadTask]);

  // ── Actions ────────────────────────────────────────────────────────────────
  async function run() {
    setBusy(true);
    setErr(null);
    setEvents([]);
    setTask(null);
    try {
      const delegateAllowed = openClaw?.delegate?.enabled === true;
      const metadata: Record<string, unknown> = {};
      if (delegateOpenClaw && delegateAllowed) {
        const agents = openclawAgentsStr
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        metadata.openclaw = {
          delegate: true,
          ...(agents.length > 0 ? { agents } : {}),
        };
      }
      let { task: t, httpStatus } = await createTask(text, {
        execution: asyncMode ? "async" : "sync",
        metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
      });
      if (httpStatus === 202 || t.status === "queued" || t.status === "running") {
        t = await waitForTerminal(t.id);
      }
      setTask(t);
      const tl = await fetchTimeline(t.id).catch(() => []);
      setEvents(tl);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      void refreshTaskList();
    }
  }

  async function retry() {
    if (!task) return;
    setBusy(true);
    setErr(null);
    try {
      let t = await retryTask(task.id, asyncMode ? "async" : "sync");
      if (t.status === "queued" || t.status === "running") {
        t = await waitForTerminal(t.id);
      }
      setTask(t);
      const tl = await fetchTimeline(t.id).catch(() => []);
      setEvents(tl);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      void refreshTaskList();
    }
  }

  async function cancel() {
    if (!task) return;
    setBusy(true);
    setErr(null);
    try {
      const t = await cancelTask(task.id);
      setTask(t);
      void refreshTaskList();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreatePolicy() {
    setPolicyErr(null);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(policyContent) as Record<string, unknown>;
    } catch {
      setPolicyErr("content must be valid JSON");
      return;
    }
    try {
      await createPolicy(policyName, parsed);
      setPolicyName("");
      setPolicyContent("{}");
      void refreshPolicies();
    } catch (e) {
      setPolicyErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeletePolicy(id: string) {
    try {
      await deletePolicy(id);
      void refreshPolicies();
    } catch {
      /* ignore */
    }
  }

  async function handleActivatePolicy(id: string) {
    try {
      await activatePolicy(id);
      void refreshPolicies();
      try {
        setPolicyLog(await fetchPolicyActivationLog(40));
      } catch {
        /* ignore */
      }
    } catch {
      /* ignore */
    }
  }

  async function handleDeactivateAll() {
    try {
      await deactivateAllPolicies();
      void refreshPolicies();
      try {
        setPolicyLog(await fetchPolicyActivationLog(40));
      } catch {
        /* ignore */
      }
    } catch {
      /* ignore */
    }
  }

  async function handleSetLevel(level: "minimal" | "balanced" | "strict") {
    setGovLevelBusy(true);
    try {
      await setGovernanceLevel(level);
      void refreshGovernance();
    } finally {
      setGovLevelBusy(false);
    }
  }

  async function handleVote(decision: "approve" | "reject") {
    if (!task) return;
    setBusy(true);
    setErr(null);
    try {
      const vid = voterId.trim() || "operator";
      let t = await castVote(task.id, vid, decision, voteNote.trim() || undefined);
      // If quorum reached, task may now be queued/running — poll to terminal.
      if (t.status === "queued" || t.status === "running") {
        t = await waitForTerminal(t.id);
      }
      setTask(t);
      const tl = await fetchTimeline(t.id).catch(() => []);
      setEvents(tl);
      setVoteNote("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      void refreshTaskList();
    }
  }

  const canCancel = task?.status === "received" || task?.status === "queued";
  const canRetry = task?.status === "failed" || task?.status === "needs_revision";
  const cf = task?.classification;
  const confPct = cf ? Math.round(cf.confidence * 100) : null;

  const EXAMPLES = [
    "Write a haiku about the ocean",
    "Summarize the top 3 risks in this sprint",
    "Draft a changelog entry for v2.0",
    "Drop the production database",
  ];

  return (
    <div className="shell">
      <header className="header">
        <span className="header-title">ClawAgora</span>
        <span className="muted header-sub">governance-aware agent kernel</span>
      </header>

      <div className="flow-guide">
        <span className="flow-step">① Write task</span>
        <span className="flow-arrow">→</span>
        <span className="flow-step">② Auto-classify <span className="flow-dim">(risk tier)</span></span>
        <span className="flow-arrow">→</span>
        <span className="flow-step flow-step-cond">③ Approval? <span className="flow-dim">(high risk)</span></span>
        <span className="flow-arrow">→</span>
        <span className="flow-step">④ Execute</span>
        <span className="flow-arrow">→</span>
        <span className="flow-step">⑤ Receipt</span>
      </div>

      <div className="layout">
        {/* ── Left: submit + detail ─────────────────────────────────────── */}
        <div className="col-primary">
          <div className="panel">
            <label className="field-label">Task input</label>
            <textarea
              value={text}
              placeholder="Describe the change you want delivered…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !busy) {
                  void run();
                }
              }}
            />
            <div className="example-chips">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  className="chip"
                  onClick={() => setText(ex)}
                  disabled={busy}
                >
                  {ex}
                </button>
              ))}
            </div>
            <div className="row" style={{ marginTop: 8, gap: 8 }}>
              <button type="button" onClick={() => void run()} disabled={busy}>
                {busy ? "Running…" : "Run"}
              </button>
              {canRetry && (
                <button type="button" onClick={() => void retry()} disabled={busy}>
                  Retry
                </button>
              )}
              {canCancel && (
                <button
                  type="button"
                  className="btn-warn"
                  onClick={() => void cancel()}
                  disabled={busy}
                >
                  Cancel
                </button>
              )}
              {status !== "idle" && (
                <span className={`status-badge status-${status}`}>{status}</span>
              )}
              {task && task.run_attempt > 0 && (
                <span className="muted">×{task.run_attempt}</span>
              )}
              <label className="muted switch-label" title="Queue mode: submit and return immediately; task runs in background via RQ worker">
                <input
                  type="checkbox"
                  checked={asyncMode}
                  onChange={(e) => setAsyncMode(e.target.checked)}
                />
                queue
              </label>
              <label
                className={`muted switch-label${
                  openClaw?.delegate?.enabled === true ? "" : " disabled"
                }`}
                title={
                  openClaw?.delegate?.enabled === true
                    ? "POST execution to an external OpenClaw-compatible HTTP bridge; the bridge must call back with HMAC (see Governance tab)."
                    : "Enable CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=1 and set CLAWAGORA_OPENCLAW_DELEGATE_URL on the server."
                }
              >
                <input
                  type="checkbox"
                  checked={delegateOpenClaw}
                  onChange={(e) => setDelegateOpenClaw(e.target.checked)}
                  disabled={openClaw?.delegate?.enabled !== true}
                />
                OpenClaw delegate
              </label>
              {delegateOpenClaw && openClaw?.delegate?.enabled === true && (
                <input
                  className="input-sm"
                  style={{ minWidth: 200, flex: "1 1 160px" }}
                  placeholder="Agents (comma-separated, optional)"
                  value={openclawAgentsStr}
                  onChange={(e) => setOpenclawAgentsStr(e.target.value)}
                  aria-label="OpenClaw agent ids"
                />
              )}
              <span className="muted hint">⌘↵ run</span>
            </div>
          </div>

          {err && (
            <div className="panel panel-err">
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{err}</pre>
            </div>
          )}

          {task && task.status === "pending_approval" && task.approval_request && (
            <ApprovalPanel
              ar={task.approval_request}
              voterId={voterId}
              voteNote={voteNote}
              busy={busy}
              onVoterIdChange={setVoterId}
              onNoteChange={setVoteNote}
              onVote={handleVote}
            />
          )}

          {!task && !busy && !err && (
            <div className="empty-state">
              <div className="empty-icon">◎</div>
              <div className="empty-title">No task selected</div>
              <div className="empty-body">
                Type a task above and hit <kbd>Run</kbd>, or click any item in the history on the right to inspect it.
                High-risk tasks (e.g. production changes, deletions) will pause for operator approval before executing.
              </div>
            </div>
          )}

          {task && (
            <div className="panel">
              <div className="task-meta row" style={{ marginBottom: 10 }}>
                <span className="pill mono">{task.id.slice(0, 8)}</span>
                <span className={`risk-badge risk-${task.risk_tier}`}>{task.risk_tier}</span>
                {cf && (
                  <span className="muted">
                    {cf.label} · {confPct}%
                  </span>
                )}
                {task.error_code && (
                  <span className="pill pill-err">{task.error_code}</span>
                )}
              </div>

              <OpenClawTaskStrip task={task} openClaw={openClaw} />

              {task.receipt && <ReceiptPanel receipt={task.receipt} />}

              <TaskTimeline events={events} />
            </div>
          )}
        </div>

        {/* ── Right: task list + policies ──────────────────────────────── */}
        <div className="col-secondary">
          <div className="tab-bar">
            <button
              type="button"
              className={`tab${rightTab === "tasks" ? " active" : ""}`}
              onClick={() => {
                setRightTab("tasks");
                void refreshTaskList();
              }}
            >
              Tasks
            </button>
            <button
              type="button"
              className={`tab${rightTab === "policies" ? " active" : ""}`}
              onClick={() => {
                setRightTab("policies");
                void refreshPolicies();
              }}
            >
              Policies
            </button>
            <button
              type="button"
              className={`tab${rightTab === "governance" ? " active" : ""}`}
              onClick={() => {
                setRightTab("governance");
                void refreshGovernance();
              }}
            >
              Governance
            </button>
          </div>

          {rightTab === "tasks" && (
            <div className="task-list">
              <div
                className="task-filter-row"
                style={{
                  padding: "6px 10px",
                  gap: 6,
                  display: "flex",
                  flexWrap: "wrap",
                  borderBottom: "1px solid #21262d",
                }}
              >
                {(["all", "judicial", "needs_revision"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={`chip${taskListFilter === f ? " chip-active" : ""}`}
                    onClick={() => setTaskListFilter(f)}
                  >
                    {f === "all" ? "All" : f === "judicial" ? "Judicial queue" : "Needs revision"}
                  </button>
                ))}
              </div>
              {taskList.length === 0 && (
                <div className="muted" style={{ padding: "10px 12px" }}>
                  No tasks yet.
                </div>
              )}
              {taskList.map((t) => (
                <div
                  key={t.id}
                  className={`task-item${task?.id === t.id ? " active" : ""}${loadingTaskId === t.id ? " loading" : ""}`}
                  onClick={() => void loadTask(t.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void loadTask(t.id);
                  }}
                >
                  <div className="row" style={{ gap: 6 }}>
                    <span className={`status-dot status-dot-${t.status}`} />
                    <span className="task-item-text">
                      {(t.input_text ?? "").length > 55
                        ? (t.input_text ?? "").slice(0, 55) + "…"
                        : (t.input_text ?? "—")}
                    </span>
                  </div>
                  <div className="task-item-meta">
                    <span className="muted" style={{ fontSize: 10 }}>
                      {t.created_at.slice(0, 16).replace("T", " ")}
                    </span>
                    <span className={`risk-badge risk-${t.risk_tier}`}>{t.risk_tier}</span>
                    {t.error_code && (
                      <span className="pill pill-err pill-sm">{t.error_code}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {rightTab === "policies" && (
            <div className="policy-panel">
              <div className="policy-list">
                {policies.length === 0 && (
                  <div className="muted" style={{ padding: "10px 12px" }}>
                    No policy drafts yet.
                  </div>
                )}
                {policyLog.length > 0 && (
                  <div style={{ padding: "8px 12px", borderBottom: "1px solid #21262d" }}>
                    <div className="field-label" style={{ marginBottom: 6 }}>
                      Legislative log
                    </div>
                    <div className="muted" style={{ fontSize: 10, maxHeight: 120, overflow: "auto" }}>
                      {policyLog.slice(0, 12).map((e) => (
                        <div key={e.id} style={{ marginBottom: 4 }}>
                          {e.created_at.slice(0, 16).replace("T", " ")} · {e.action}
                          {e.policy_draft_id ? ` · ${String(e.policy_draft_id).slice(0, 8)}` : ""}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {policies.map((p) => (
                  <div key={p.id} className={`policy-item${p.is_active ? " policy-active" : ""}`}>
                    <div className="policy-item-left">
                      {p.is_active && <span className="policy-active-dot" title="Active" />}
                      <span className="policy-name">{p.name}</span>
                    </div>
                    <div className="row" style={{ gap: 4, flexShrink: 0 }}>
                      {!p.is_active ? (
                        <button
                          type="button"
                          className="btn-activate"
                          title="Activate this policy"
                          onClick={() => void handleActivatePolicy(p.id)}
                        >
                          Activate
                        </button>
                      ) : (
                        <span className="policy-active-label">active</span>
                      )}
                      <button
                        type="button"
                        className="btn-icon"
                        title="Delete"
                        onClick={() => void handleDeletePolicy(p.id)}
                      >
                        ×
                      </button>
                    </div>
                  </div>
                ))}
                {policies.some((p) => p.is_active) && (
                  <div style={{ padding: "6px 12px 8px" }}>
                    <button
                      type="button"
                      className="btn-sm btn-deactivate"
                      onClick={() => void handleDeactivateAll()}
                    >
                      Deactivate all
                    </button>
                  </div>
                )}
              </div>

              <div className="policy-help">
                Policies are JSON rules injected into every task's governance context.
                They influence validation and approval decisions.
                Example: <code className="code-inline">&#123;"require_rationale": true&#125;</code>
              </div>

              <div className="policy-form">
                <input
                  className="input-sm"
                  placeholder="Policy name  (e.g. require-rationale)"
                  value={policyName}
                  onChange={(e) => setPolicyName(e.target.value)}
                />
                <textarea
                  className="textarea-sm"
                  placeholder='{"require_rationale": true}'
                  value={policyContent}
                  onChange={(e) => setPolicyContent(e.target.value)}
                />
                {policyErr && (
                  <div className="muted" style={{ color: "#cf222e" }}>
                    {policyErr}
                  </div>
                )}
                <button
                  type="button"
                  className="btn-sm"
                  onClick={() => void handleCreatePolicy()}
                  disabled={!policyName.trim()}
                >
                  Add policy
                </button>
              </div>
            </div>
          )}

          {rightTab === "governance" && (
            <GovernancePanel
              profiles={govProfiles}
              dashboard={govDashboard}
              openClaw={openClaw}
              busy={govLevelBusy}
              onSetLevel={handleSetLevel}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function OpenClawTaskStrip({
  task,
  openClaw,
}: {
  task: TaskRecord;
  openClaw: OpenClawStatus | null;
}) {
  const oc = task.metadata?.openclaw;
  if (!oc || typeof oc !== "object" || oc === null) return null;
  const raw = oc as { delegate?: boolean; phase?: string; agents?: unknown };
  const phase = raw.phase ?? "";
  const agents = Array.isArray(raw.agents) ? raw.agents.map((a) => String(a)) : [];
  if (!raw.delegate && !phase) return null;

  return (
    <div
      className="openclaw-strip"
      style={{
        marginBottom: 12,
        padding: "10px 12px",
        border: "1px solid #223042",
        borderRadius: 6,
        background: "#0d1117",
      }}
    >
      <div className="field-label" style={{ marginBottom: 6 }}>
        OpenClaw
      </div>
      {raw.delegate && (
        <div className="muted" style={{ fontSize: 11 }}>
          Delegate mode: execution is routed to the external HTTP bridge.
        </div>
      )}
      {phase ? (
        <div className="gov-stat-row">
          <span className="gov-stat-label">Phase</span>
          <span className="gov-stat-value">{phase}</span>
        </div>
      ) : null}
      {agents.length > 0 ? (
        <div className="gov-stat-row">
          <span className="gov-stat-label">Agents</span>
          <span className="gov-stat-value mono" style={{ fontSize: 10 }}>
            {agents.join(", ")}
          </span>
        </div>
      ) : null}
      {phase === "awaiting_callback" && openClaw?.delegate?.callback_url ? (
        <div className="muted" style={{ fontSize: 10, marginTop: 6 }}>
          Waiting for bridge callback (HMAC) to{" "}
          <span className="mono">{openClaw.delegate.callback_url}</span>
        </div>
      ) : null}
    </div>
  );
}

const LEVEL_DESC: Record<string, { label: string; desc: string; color: string }> = {
  minimal: {
    label: "Minimal",
    desc: "Fast execution, baseline checks only. Low overhead.",
    color: "#3fb950",
  },
  balanced: {
    label: "Balanced",
    desc: "Strong risk control with moderate latency. Recommended default.",
    color: "#e3a008",
  },
  strict: {
    label: "Strict",
    desc: "Maximum governance. Slow but highly auditable. Use for production.",
    color: "#ff7b7b",
  },
};

function GovernancePanel({
  profiles,
  dashboard,
  openClaw,
  busy,
  onSetLevel,
}: {
  profiles: GovernanceProfiles | null;
  dashboard: GovernanceDashboard | null;
  openClaw: OpenClawStatus | null;
  busy: boolean;
  onSetLevel: (level: "minimal" | "balanced" | "strict") => void;
}) {
  const [copiedCallback, setCopiedCallback] = useState(false);
  const currentLevel = profiles?.selected_level ?? dashboard?.governance_level ?? "balanced";
  const alertCount = dashboard?.alerts?.length ?? 0;
  const deleg = openClaw?.delegate;

  return (
    <div className="gov-panel">
      <div className="gov-section-title">Governance Level</div>
      <div className="gov-help">
        Controls how strictly this system validates, approves, and audits every task.
      </div>
      <div className="gov-levels">
        {(["minimal", "balanced", "strict"] as const).map((lvl) => {
          const meta = LEVEL_DESC[lvl];
          const card = profiles?.cards.find((c) => c.level === lvl);
          const selected = currentLevel === lvl;
          return (
            <button
              key={lvl}
              type="button"
              className={`gov-level-card${selected ? " selected" : ""}`}
              style={selected ? { borderColor: meta.color } : undefined}
              disabled={busy || selected}
              onClick={() => onSetLevel(lvl)}
            >
              <div className="gov-level-header">
                <span className="gov-level-name" style={{ color: selected ? meta.color : undefined }}>
                  {meta.label}
                </span>
                {selected && <span className="gov-level-badge">active</span>}
              </div>
              <div className="gov-level-desc">{meta.desc}</div>
              {card && (
                <div className="gov-level-meta">
                  <span>latency: {card.latency_estimate}</span>
                  <span>risk: {card.risk_control}</span>
                </div>
              )}
            </button>
          );
        })}
      </div>

      {openClaw && (
        <>
          <div className="gov-section-title" style={{ marginTop: 14 }}>OpenClaw gateway</div>
          <div className="gov-stat-row">
            <span className="gov-stat-label">Probe</span>
            <span className="gov-stat-value">
              {openClaw.enabled
                ? openClaw.reachable
                  ? `reachable ${openClaw.latency_ms != null ? `(${openClaw.latency_ms}ms)` : ""}`
                  : "unreachable"
                : "disabled"}
            </span>
          </div>
          {openClaw.gateway_url && (
            <div className="gov-stat-row">
              <span className="gov-stat-label">URL</span>
              <span className="gov-stat-value mono" style={{ fontSize: 10 }}>
                {openClaw.gateway_url}
              </span>
            </div>
          )}

          {deleg && (
            <>
              <div className="gov-section-title" style={{ marginTop: 14 }}>OpenClaw delegate (bridge)</div>
              <div className="gov-help" style={{ marginBottom: 8 }}>
                Server-side flags route approved work to an HTTP bridge; the bridge runs your OpenClaw agents and POSTs
                back with <span className="mono">X-ClawAgora-Signature</span>.
              </div>
              <div className="gov-stat-row">
                <span className="gov-stat-label">Delegate</span>
                <span className="gov-stat-value">{deleg.enabled ? "enabled" : "disabled"}</span>
              </div>
              <div className="gov-stat-row">
                <span className="gov-stat-label">Bridge URL</span>
                <span className="gov-stat-value">
                  {deleg.url_configured ? "configured" : "missing — set CLAWAGORA_OPENCLAW_DELEGATE_URL"}
                </span>
              </div>
              {deleg.delegate_url ? (
                <div className="gov-stat-row">
                  <span className="gov-stat-label">POST</span>
                  <span className="gov-stat-value mono" style={{ fontSize: 10 }}>
                    {deleg.delegate_url}
                  </span>
                </div>
              ) : null}
              <div className="gov-stat-row">
                <span className="gov-stat-label">Webhook HMAC</span>
                <span className="gov-stat-value">
                  {deleg.webhook_secret_configured ? "secret set" : "not set — callbacks rejected"}
                </span>
              </div>
              <div className="gov-stat-row">
                <span className="gov-stat-label">Timeout</span>
                <span className="gov-stat-value">{deleg.delegate_timeout_sec}s</span>
              </div>
              {deleg.knowledge && (
                <div className="gov-stat-row">
                  <span className="gov-stat-label">Knowledge pins</span>
                  <span className="gov-stat-value">
                    sha256: {deleg.knowledge.capability_require_sha256 ? "required" : "optional"}
                    {" · "}
                    source URL: {deleg.knowledge.capability_require_source_url ? "required" : "optional"}
                  </span>
                </div>
              )}
              {deleg.agent_config.default_agents.length > 0 || deleg.agent_config.by_risk_tiers.length > 0 ? (
                <div className="gov-stat-row" style={{ alignItems: "flex-start" }}>
                  <span className="gov-stat-label">Agents</span>
                  <span className="gov-stat-value mono" style={{ fontSize: 10 }}>
                    defaults: {deleg.agent_config.default_agents.join(", ") || "—"}
                    <br />
                    by_risk: {deleg.agent_config.by_risk_tiers.join(", ") || "—"}
                  </span>
                </div>
              ) : null}
              {deleg.callback_url ? (
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <span className="gov-stat-value mono" style={{ fontSize: 10, wordBreak: "break-all" }}>
                    {deleg.callback_url}
                  </span>
                  <button
                    type="button"
                    className="btn-sm"
                    onClick={() => {
                      void navigator.clipboard.writeText(deleg.callback_url ?? "").then(() => {
                        setCopiedCallback(true);
                        window.setTimeout(() => setCopiedCallback(false), 2000);
                      });
                    }}
                  >
                    {copiedCallback ? "Copied" : "Copy callback URL"}
                  </button>
                </div>
              ) : (
                <div className="muted" style={{ fontSize: 10, marginTop: 8 }}>
                  Set <span className="mono">CLAWAGORA_PUBLIC_BASE_URL</span> so delegate payloads include a callback URL.
                </div>
              )}
            </>
          )}
        </>
      )}

      {dashboard && (
        <>
          <div className="gov-section-title" style={{ marginTop: 14 }}>System Status</div>
          <div className="gov-stat-row">
            <span className="gov-stat-label">Profile</span>
            <span className="gov-stat-value">{dashboard.profile}</span>
          </div>
          <div className="gov-stat-row">
            <span className="gov-stat-label">Daily budget</span>
            <span className="gov-stat-value">{(dashboard.daily_budget * 100).toFixed(0)}%</span>
          </div>
          <div className="gov-stat-row">
            <span className="gov-stat-label">Alerts</span>
            <span className={`gov-stat-value${alertCount > 0 ? " gov-alert" : ""}`}>
              {alertCount === 0 ? "none" : alertCount}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function ApprovalPanel({
  ar,
  voterId,
  voteNote,
  busy,
  onVoterIdChange,
  onNoteChange,
  onVote,
}: {
  ar: ApprovalRequest;
  voterId: string;
  voteNote: string;
  busy: boolean;
  onVoterIdChange: (v: string) => void;
  onNoteChange: (v: string) => void;
  onVote: (decision: "approve" | "reject") => void;
}) {
  const threshold = ar.threshold;
  return (
    <div className="panel approval-panel">
      <div className="row" style={{ marginBottom: 6, gap: 8 }}>
        <span className={`risk-badge risk-${ar.risk_tier}`}>{ar.risk_tier}</span>
        <span className="muted" style={{ fontSize: 11 }}>awaiting approval</span>
      </div>
      {ar.summary && (
        <p className="approval-summary">{ar.summary}</p>
      )}
      <div className="approval-quorum row" style={{ marginBottom: 8, gap: 10 }}>
        <span className="approval-vote-count approve">
          ✓ {ar.approve_count}/{threshold}
        </span>
        <span className="approval-vote-count reject">
          ✗ {ar.reject_count}/{threshold}
        </span>
        <span className="muted" style={{ fontSize: 10 }}>
          quorum {ar.quorum}
        </span>
      </div>
      <div className="row" style={{ gap: 6, marginBottom: 6 }}>
        <input
          className="input-sm"
          style={{ flex: 1 }}
          placeholder="voter id"
          value={voterId}
          onChange={(e) => onVoterIdChange(e.target.value)}
        />
      </div>
      <textarea
        className="textarea-sm"
        placeholder="note (optional)"
        value={voteNote}
        onChange={(e) => onNoteChange(e.target.value)}
        style={{ minHeight: 40, marginBottom: 6 }}
      />
      <div className="row" style={{ gap: 6 }}>
        <button
          type="button"
          className="btn-approve"
          disabled={busy || !voterId.trim()}
          onClick={() => onVote("approve")}
        >
          Approve
        </button>
        <button
          type="button"
          className="btn-reject"
          disabled={busy || !voterId.trim()}
          onClick={() => onVote("reject")}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

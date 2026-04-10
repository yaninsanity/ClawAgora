import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  activatePolicy,
  cancelTask,
  castVote,
  createPolicy,
  createTask,
  deactivateAllPolicies,
  deletePolicy,
  updatePolicy,
  fetchGovernanceExecutors,
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
  type GovernanceSummary,
  type OpenClawStatus,
  type PolicyActivationLogEntry,
  type PolicyDraft,
  type TaskListItem,
  type TaskRecord,
  type TimelineEvent,
} from "./api/client";
import { FirstRunOnboarding } from "./components/FirstRunOnboarding";
import { OptionalProductHelp } from "./components/OptionalProductHelp";
import {
  PolicyLegislativeForm,
  buildPolicyContentFromForm,
  emptyLegislativeFormState,
  formUsesAdvancedFields,
  legislativeFormFromPolicyContent,
  mergeExecutorOptions,
  POLICY_EXECUTOR_FALLBACK,
  type LegislativeFormState,
  type PolicyExecutorOption,
} from "./components/PolicyLegislativeForm";
import { JudicialQuorumCard } from "./components/JudicialQuorumCard";
import { PolicyProposalsPanel } from "./components/PolicyProposalsPanel";
import { ReceiptPanel } from "./components/ReceiptPanel";
import { OpenClawArtifactsList } from "./components/OpenClawArtifactsList";
import { TaskTimeline } from "./components/TaskTimeline";
import { loadPromptRegistryOpen, savePromptRegistryOpen } from "./governance/promptRegistryStorage";
import { useGovernanceRefresh } from "./hooks/useGovernanceRefresh";
import { isOnboardingDismissed, resetOnboardingDismissal } from "./onboardingStorage";

type RightTab = "tasks" | "policies" | "governance";
type TaskListFilter = "all" | "judicial" | "needs_revision";

const WORKSPACE_TAB_ORDER: RightTab[] = ["tasks", "policies", "governance"];

const TAB_PANEL_ID: Record<RightTab, string> = {
  tasks: "panel-tasks",
  policies: "panel-policies",
  governance: "panel-governance",
};

const TAB_BUTTON_ID: Record<RightTab, string> = {
  tasks: "tab-tasks",
  policies: "tab-policies",
  governance: "tab-governance",
};

const TASK_STATUS_LABELS: Record<string, string> = {
  idle: "Idle",
  received: "Received",
  queued: "Queued",
  running: "Running",
  pending_approval: "Pending approval",
  needs_revision: "Needs revision",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function taskStatusLabel(code: string): string {
  return TASK_STATUS_LABELS[code] ?? code.replace(/_/g, " ");
}

const RISK_TIER_LABELS: Record<string, string> = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
};

function riskTierLabel(tier: string): string {
  return RISK_TIER_LABELS[tier] ?? `${tier} risk`;
}

/** Matches server-seeded draft from migration 0014; safe for users to delete. */
function isSeedPolicyDraft(p: PolicyDraft): boolean {
  return (
    p.name.includes("(seed)") ||
    p.content._clawagora_seed === true ||
    p.content._clawagora_seed === "true"
  );
}

export function App() {
  // ── Submit panel ──────────────────────────────────────────────────────────
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [asyncMode, setAsyncMode] = useState(false);
  const [delegateOpenClaw, setDelegateOpenClaw] = useState(false);
  const [openclawAgentsStr, setOpenclawAgentsStr] = useState("");
  const [contextSessionId, setContextSessionId] = useState("");
  const [contextCorrelationId, setContextCorrelationId] = useState("");
  const [contextMemoryRefsStr, setContextMemoryRefsStr] = useState("");
  const [err, setErr] = useState<string | null>(null);

  // ── Active task detail ─────────────────────────────────────────────────────
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [timelineLoadError, setTimelineLoadError] = useState<string | null>(null);
  const [loadingTaskId, setLoadingTaskId] = useState<string | null>(null);

  // ── Right-panel state ──────────────────────────────────────────────────────
  const [rightTab, setRightTab] = useState<RightTab>("tasks");
  const [taskList, setTaskList] = useState<TaskListItem[]>([]);
  const [policies, setPolicies] = useState<PolicyDraft[]>([]);
  const [policyName, setPolicyName] = useState("");
  const [policyExecutorsApi, setPolicyExecutorsApi] = useState<PolicyExecutorOption[] | null>(null);
  const [policyLegislativeForm, setPolicyLegislativeForm] = useState<LegislativeFormState>(() =>
    emptyLegislativeFormState(POLICY_EXECUTOR_FALLBACK.map((o) => o.id)),
  );
  const [policyErr, setPolicyErr] = useState<string | null>(null);
  const [policyFeedback, setPolicyFeedback] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const policyFeedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const {
    govProfiles,
    govDashboard,
    govSummary,
    govSummaryFailed,
    govSummaryRetrying,
    govRefreshing,
    openClaw,
    refreshGovernance,
  } = useGovernanceRefresh();
  const [govLevelBusy, setGovLevelBusy] = useState(false);
  const [policyLog, setPolicyLog] = useState<PolicyActivationLogEntry[]>([]);
  const [editingPolicyId, setEditingPolicyId] = useState<string | null>(null);
  const [policyFormInitialAdvancedOpen, setPolicyFormInitialAdvancedOpen] = useState(false);
  const policyFormSectionRef = useRef<HTMLDivElement | null>(null);
  const [taskListFilter, setTaskListFilter] = useState<TaskListFilter>("all");
  const [taskListCount, setTaskListCount] = useState<number | null>(null);
  const [taskSearchInput, setTaskSearchInput] = useState("");
  const [taskSearchQuery, setTaskSearchQuery] = useState("");
  const [taskIdCopyFeedback, setTaskIdCopyFeedback] = useState(false);
  const taskSearchFieldId = useId();
  const [taskListLoadError, setTaskListLoadError] = useState<string | null>(null);
  const [policyListLoadError, setPolicyListLoadError] = useState<string | null>(null);
  const [policyLogLoadError, setPolicyLogLoadError] = useState<string | null>(null);
  const [onboardingVisible, setOnboardingVisible] = useState(() => !isOnboardingDismissed());

  const mergedExecutorOptions = useMemo(
    () => mergeExecutorOptions(policyExecutorsApi),
    [policyExecutorsApi],
  );
  const mergedExecutorIds = useMemo(
    () => mergedExecutorOptions.map((o) => o.id),
    [mergedExecutorOptions],
  );

  useEffect(() => {
    void fetchGovernanceExecutors()
      .then((r) => setPolicyExecutorsApi(r.executors))
      .catch(() => setPolicyExecutorsApi(null));
  }, []);

  const executorAllowlistSyncedRef = useRef(false);
  useEffect(() => {
    if (!policyExecutorsApi?.length || executorAllowlistSyncedRef.current) return;
    executorAllowlistSyncedRef.current = true;
    setPolicyLegislativeForm((s) => ({
      ...s,
      allowedExecutorIds: mergedExecutorIds,
    }));
  }, [policyExecutorsApi, mergedExecutorIds]);

  // ── Approval state ─────────────────────────────────────────────────────────
  const [voterId, setVoterId] = useState("operator");
  const [voteNote, setVoteNote] = useState("");

  const status = useMemo(() => task?.status ?? "idle", [task]);

  const copyTaskIdToClipboard = useCallback((id: string) => {
    void navigator.clipboard.writeText(id).then(() => {
      setTaskIdCopyFeedback(true);
      window.setTimeout(() => setTaskIdCopyFeedback(false), 2000);
    });
  }, []);

  // ── Helpers ────────────────────────────────────────────────────────────────
  const refreshTaskList = useCallback(async () => {
    try {
      const params: Parameters<typeof listTasks>[0] = { limit: 50 };
      if (taskListFilter === "judicial") params.judicial_queue = true;
      else if (taskListFilter === "needs_revision") params.status = "needs_revision";
      if (taskSearchQuery) params.q = taskSearchQuery;
      const { results, count } = await listTasks(params);
      setTaskList(results);
      setTaskListCount(count);
      setTaskListLoadError(null);
    } catch (e) {
      setTaskListLoadError(e instanceof Error ? e.message : String(e));
    }
  }, [taskListFilter, taskSearchQuery]);

  const refreshPolicies = useCallback(async () => {
    try {
      setPolicies(await listPolicies());
      setPolicyListLoadError(null);
    } catch (e) {
      setPolicyListLoadError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refreshPolicyLog = useCallback(async () => {
    try {
      setPolicyLog(await fetchPolicyActivationLog(40));
      setPolicyLogLoadError(null);
    } catch (e) {
      setPolicyLog([]);
      setPolicyLogLoadError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const cancelPolicyEdit = useCallback(() => {
    setEditingPolicyId(null);
    setPolicyFormInitialAdvancedOpen(false);
    setPolicyName("");
    setPolicyLegislativeForm(emptyLegislativeFormState(mergedExecutorIds));
    setPolicyErr(null);
  }, [mergedExecutorIds]);

  const beginEditPolicy = useCallback(
    (p: PolicyDraft) => {
      const nextForm = legislativeFormFromPolicyContent(p.content, mergedExecutorOptions);
      setPolicyFormInitialAdvancedOpen(formUsesAdvancedFields(nextForm));
      setPolicyName(p.name);
      setPolicyLegislativeForm(nextForm);
      setEditingPolicyId(p.id);
      setPolicyErr(null);
      setRightTab("policies");
      requestAnimationFrame(() => {
        policyFormSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    },
    [mergedExecutorOptions],
  );

  const applyTimelineForTask = useCallback(async (taskId: string) => {
    try {
      const tl = await fetchTimeline(taskId);
      setTimelineLoadError(null);
      setEvents(tl);
    } catch (e) {
      setTimelineLoadError(e instanceof Error ? e.message : String(e));
      setEvents([]);
    }
  }, []);

  const loadTask = useCallback(
    async (id: string) => {
      setLoadingTaskId(id);
      setErr(null);
      try {
        const t = await fetchTask(id);
        setTask(t);
        await applyTimelineForTask(id);
      } catch (e) {
        setTask(null);
        setEvents([]);
        setTimelineLoadError(null);
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setLoadingTaskId(null);
      }
    },
    [applyTimelineForTask],
  );

  useEffect(() => {
    void refreshPolicies();
    void refreshGovernance();
  }, [refreshPolicies, refreshGovernance]);

  useEffect(
    () => () => {
      if (policyFeedbackTimerRef.current) {
        clearTimeout(policyFeedbackTimerRef.current);
        policyFeedbackTimerRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    const id = window.setTimeout(() => {
      setTaskSearchQuery(taskSearchInput.trim());
    }, 350);
    return () => window.clearTimeout(id);
  }, [taskSearchInput]);

  useEffect(() => {
    void refreshTaskList();
  }, [taskListFilter, taskSearchQuery, refreshTaskList]);

  useEffect(() => {
    if (rightTab !== "policies") return;
    void refreshPolicyLog();
  }, [rightTab, refreshPolicyLog]);

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

  // When opening a task that already has stored context, mirror it into the advanced fields (retry / same session).
  useEffect(() => {
    if (!task) return;
    const ctx = task.metadata?.clawagora_context;
    if (!ctx || typeof ctx !== "object" || Array.isArray(ctx)) return;
    const c = ctx as Record<string, unknown>;
    const sid = typeof c.session_id === "string" ? c.session_id.trim() : "";
    const corr = typeof c.correlation_id === "string" ? c.correlation_id.trim() : "";
    const refs = Array.isArray(c.memory_refs)
      ? c.memory_refs.filter((x): x is string => typeof x === "string").map((s) => s.trim()).filter(Boolean)
      : [];
    if (!sid && !corr && refs.length === 0) return;
    setContextSessionId(sid);
    setContextCorrelationId(corr);
    setContextMemoryRefsStr(refs.join(", "));
  }, [task?.id]);

  // ── Actions ────────────────────────────────────────────────────────────────
  async function run() {
    setBusy(true);
    setErr(null);
    setTimelineLoadError(null);
    setEvents([]);
    setTask(null);
    try {
      const delegateAllowed = openClaw?.delegate?.enabled === true;
      const metadata: Record<string, unknown> = {};
      const sid = contextSessionId.trim();
      const corr = contextCorrelationId.trim();
      const memRefs = contextMemoryRefsStr
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (sid || corr || memRefs.length > 0) {
        metadata.clawagora_context = {
          ...(sid ? { session_id: sid } : {}),
          ...(corr ? { correlation_id: corr } : {}),
          ...(memRefs.length > 0 ? { memory_refs: memRefs } : {}),
        };
      }
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
      await applyTimelineForTask(t.id);
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
    setTimelineLoadError(null);
    try {
      let t = await retryTask(task.id, asyncMode ? "async" : "sync");
      if (t.status === "queued" || t.status === "running") {
        t = await waitForTerminal(t.id);
      }
      setTask(t);
      await applyTimelineForTask(t.id);
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
      await applyTimelineForTask(t.id);
      void refreshTaskList();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleSavePolicy() {
    setPolicyErr(null);
    setPolicyFeedback(null);
    if (policyFeedbackTimerRef.current) {
      clearTimeout(policyFeedbackTimerRef.current);
      policyFeedbackTimerRef.current = null;
    }
    const built = buildPolicyContentFromForm(policyLegislativeForm, mergedExecutorIds);
    if (!built.ok) {
      setPolicyErr(built.error);
      return;
    }
    const nameTrim = policyName.trim();
    try {
      if (editingPolicyId) {
        await updatePolicy(editingPolicyId, { name: nameTrim, content: built.content });
        void refreshPolicies();
        void refreshPolicyLog();
        setPolicyFeedback({
          kind: "success",
          message: "Draft updated. If it is on, new tasks already use the latest rules.",
        });
      } else {
        await createPolicy(nameTrim, built.content);
        setPolicyName("");
        setPolicyLegislativeForm(emptyLegislativeFormState(mergedExecutorIds));
        void refreshPolicies();
        void refreshPolicyLog();
        setPolicyFeedback({
          kind: "success",
          message: "Draft saved. Find it in the list above — press Turn on when you want new tasks to use it.",
        });
      }
      if (policyFeedbackTimerRef.current) clearTimeout(policyFeedbackTimerRef.current);
      policyFeedbackTimerRef.current = setTimeout(() => {
        setPolicyFeedback((f) => (f?.kind === "success" ? null : f));
        policyFeedbackTimerRef.current = null;
      }, 8000);
    } catch (e) {
      setPolicyErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeletePolicy(id: string) {
    setPolicyFeedback(null);
    if (policyFeedbackTimerRef.current) {
      clearTimeout(policyFeedbackTimerRef.current);
      policyFeedbackTimerRef.current = null;
    }
    try {
      await deletePolicy(id);
      if (id === editingPolicyId) {
        cancelPolicyEdit();
      }
      void refreshPolicies();
      setPolicyFeedback({ kind: "success", message: "Draft removed." });
      policyFeedbackTimerRef.current = setTimeout(() => {
        setPolicyFeedback((f) => (f?.kind === "success" ? null : f));
        policyFeedbackTimerRef.current = null;
      }, 5000);
    } catch (e) {
      setPolicyFeedback({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }

  async function handleActivatePolicy(id: string) {
    setPolicyFeedback(null);
    if (policyFeedbackTimerRef.current) {
      clearTimeout(policyFeedbackTimerRef.current);
      policyFeedbackTimerRef.current = null;
    }
    try {
      await activatePolicy(id);
      void refreshPolicies();
      void refreshPolicyLog();
      setPolicyFeedback({ kind: "success", message: "Rules are on for new tasks." });
      policyFeedbackTimerRef.current = setTimeout(() => {
        setPolicyFeedback((f) => (f?.kind === "success" ? null : f));
        policyFeedbackTimerRef.current = null;
      }, 6000);
    } catch (e) {
      setPolicyFeedback({
        kind: "error",
        message: e instanceof Error ? e.message : "Could not turn rules on. Check permissions or try again.",
      });
    }
  }

  async function handleTurnOffActivePolicy() {
    setPolicyFeedback(null);
    if (policyFeedbackTimerRef.current) {
      clearTimeout(policyFeedbackTimerRef.current);
      policyFeedbackTimerRef.current = null;
    }
    try {
      await deactivateAllPolicies();
      void refreshPolicies();
      void refreshPolicyLog();
      setPolicyFeedback({
        kind: "success",
        message: "Rule set turned off. New tasks use defaults until you turn a draft on again.",
      });
      policyFeedbackTimerRef.current = setTimeout(() => {
        setPolicyFeedback((f) => (f?.kind === "success" ? null : f));
        policyFeedbackTimerRef.current = null;
      }, 6000);
    } catch (e) {
      setPolicyFeedback({
        kind: "error",
        message: e instanceof Error ? e.message : "Could not turn off rules. Try again.",
      });
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
    setTimelineLoadError(null);
    try {
      const vid = voterId.trim() || "operator";
      let t = await castVote(task.id, vid, decision, voteNote.trim() || undefined);
      // If quorum reached, task may now be queued/running — poll to terminal.
      if (t.status === "queued" || t.status === "running") {
        t = await waitForTerminal(t.id);
      }
      setTask(t);
      await applyTimelineForTask(t.id);
      setVoteNote("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      void refreshTaskList();
    }
  }

  const selectWorkspaceTab = useCallback(
    (tab: RightTab) => {
      setRightTab(tab);
      if (tab === "tasks") void refreshTaskList();
      else if (tab === "policies") void refreshPolicies();
      else void refreshGovernance();
    },
    [refreshTaskList, refreshPolicies, refreshGovernance],
  );

  const focusTabButton = useCallback((tab: RightTab) => {
    queueMicrotask(() => {
      document.getElementById(TAB_BUTTON_ID[tab])?.focus();
    });
  }, []);

  const onWorkspaceTabKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const i = WORKSPACE_TAB_ORDER.indexOf(rightTab);
      if (i < 0) return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        const next = WORKSPACE_TAB_ORDER[(i + 1) % WORKSPACE_TAB_ORDER.length];
        selectWorkspaceTab(next);
        focusTabButton(next);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        const next =
          WORKSPACE_TAB_ORDER[(i - 1 + WORKSPACE_TAB_ORDER.length) % WORKSPACE_TAB_ORDER.length];
        selectWorkspaceTab(next);
        focusTabButton(next);
      } else if (e.key === "Home") {
        e.preventDefault();
        const next = WORKSPACE_TAB_ORDER[0];
        selectWorkspaceTab(next);
        focusTabButton(next);
      } else if (e.key === "End") {
        e.preventDefault();
        const next = WORKSPACE_TAB_ORDER[WORKSPACE_TAB_ORDER.length - 1];
        selectWorkspaceTab(next);
        focusTabButton(next);
      }
    },
    [rightTab, selectWorkspaceTab, focusTabButton],
  );

  const canCancel = task?.status === "received" || task?.status === "queued";
  const canRetry = task?.status === "failed" || task?.status === "needs_revision";
  const cf = task?.classification;
  const confPct = cf ? Math.round(cf.confidence * 100) : null;

  const EXAMPLES = [
    "Goal: one-page exec brief on Q3 risks — 3 bullets, 1 recommendation, plain language",
    "Summarize the top 3 risks in this sprint for stand-up (5 bullets max)",
    "Draft a changelog entry for v2.0 suitable for customers",
    "Write a haiku about the ocean",
  ];

  return (
    <div className="shell">
      <div className="skip-links" role="navigation" aria-label="Skip links">
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        <a href="#workspace-sidebar" className="skip-link skip-link-secondary">
          Skip to workspace
        </a>
        {!onboardingVisible ? (
          <a href="#optional-help" className="skip-link skip-link-tertiary">
            Skip to quick reference
          </a>
        ) : null}
      </div>
      <header className="header" role="banner">
        <h1 className="header-title">ClawAgora</h1>
        <div className="header-copy">
          <p className="header-lead">
            <strong>State a clear goal</strong>, send it to the agent, then <strong>manage</strong> the run from{" "}
            <strong>Progress</strong> and <strong>Review</strong>. You get <strong>traceable stages</strong> and, on
            success, a <strong>receipt</strong> you can audit. Use <strong>Rules</strong> / <strong>Safety</strong> when
            you need tighter control.
          </p>
          {!onboardingVisible ? (
            <p className="header-help-jump">
              <a href="#optional-help" className="header-help-jump-link">
                Quick reference
              </a>
              <span className="muted header-help-jump-sep" aria-hidden="true">
                {" "}
                ·{" "}
              </span>
              <a href="#main-content" className="header-help-jump-link">
                Jump to request form
              </a>
            </p>
          ) : null}
          <details className="header-more-details">
            <summary className="product-help-summary header-more-summary disclosure-summary-a11y">
              More product detail (optional)
            </summary>
            <div className="header-more-body">
              <p className="muted">
                Built for <strong>operators and reviewers</strong>, not only engineers. Same coverage as fixed-department
                consoles (inbox, policy, dispatch, audit) with <strong>separated surfaces</strong>:{" "}
                <strong>Rules</strong> (legislative), <strong>Send request + Progress</strong> (executive),{" "}
                <strong>Review + Safety</strong> (judicial). Optional <strong>OpenClaw</strong> for external bridges.
              </p>
              <p className="header-sub header-sub-tech muted">
                Live API on this host (<code className="code-inline">Task</code>, <code className="code-inline">TaskEvent</code>
                ). Layout: left — send requests; right — Review, Rules, Safety.
              </p>
            </div>
          </details>
        </div>
      </header>

      {onboardingVisible ? (
        <FirstRunOnboarding
          onOpenReviewTab={() => {
            setRightTab("tasks");
            void refreshTaskList();
          }}
          onOpenRulesTab={() => {
            setRightTab("policies");
            void refreshPolicies();
          }}
          onDismissed={() => setOnboardingVisible(false)}
        />
      ) : null}

      <div className="layout">
        {/* ── Left: submit + detail ─────────────────────────────────────── */}
        <main id="main-content" className="col-primary" tabIndex={-1} aria-label="Goals, agent runs, and outcomes">
          <fieldset className="panel panel--task-entry task-fieldset">
            <legend className="task-fieldset-legend">Goal for this run</legend>
            <p className="task-goal-chain muted" aria-hidden="true">
              <span className="task-goal-chain-step">Goal</span>
              <span className="task-goal-chain-arrow">→</span>
              <span className="task-goal-chain-step">Agent stages</span>
              <span className="task-goal-chain-arrow">→</span>
              <span className="task-goal-chain-step">Outcome &amp; receipt</span>
            </p>
            <label className="field-label field-label--friendly" htmlFor="task-input-main">
              What outcome should the agent deliver?
            </label>
            <textarea
              id="task-input-main"
              value={text}
              placeholder="Be specific: audience, format, constraints, and done-when. Example: one-page brief for leadership on Q3 risks — 3 bullets, 1 recommendation, no jargon."
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !busy) {
                  void run();
                }
              }}
              aria-describedby="task-goal-primer task-input-format-hint"
            />
            <p id="task-goal-primer" className="field-hint-goal">
              A precise goal makes planning and validation match what you need. Manage every run in <strong>Review</strong>;
              tighten behavior with <strong>Rules</strong> when required.
            </p>
            <p id="task-input-format-hint" className="field-hint-friendly">
              After <strong>Send request</strong>, watch <strong>Progress</strong> below, then <strong>Outcome</strong> and
              the <strong>receipt</strong> when the run completes successfully.
            </p>
            <div className="example-chips example-chips-compact">
              <label className="example-chips-label" htmlFor="task-example-select">
                Not sure what to type?
              </label>
              <select
                id="task-example-select"
                className="example-chips-select"
                value=""
                onChange={(e) => {
                  const v = e.target.value;
                  if (v) setText(v);
                  e.target.value = "";
                }}
                disabled={busy}
                aria-label="Insert a sample prompt"
              >
                <option value="">Insert an example…</option>
                {EXAMPLES.map((ex) => (
                  <option key={ex} value={ex}>
                    {ex.length > 48 ? `${ex.slice(0, 48)}…` : ex}
                  </option>
                ))}
              </select>
            </div>
            <div className="task-run-actions">
              <div className="row" style={{ marginTop: 8, gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <button
                  type="button"
                  className="btn-run-primary"
                  onClick={() => void run()}
                  disabled={busy}
                  aria-busy={busy}
                >
                  {busy ? "Sending…" : "Send request"}
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
                  <span
                    className={`status-badge status-${status}`}
                    aria-live="polite"
                    aria-atomic="true"
                    title={taskStatusLabel(status)}
                  >
                    {taskStatusLabel(status)}
                  </span>
                )}
                {task && task.run_attempt > 0 && (
                  <span className="muted">×{task.run_attempt}</span>
                )}
              </div>
              <details className="task-advanced-details">
                <summary className="task-advanced-summary disclosure-summary-a11y">
                  Advanced — background run or OpenClaw (optional)
                </summary>
                <div className="task-advanced-inner task-advanced-inner--stack">
                  <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <label
                    className="muted switch-label"
                    htmlFor="task-async-queue"
                    title="Submit and return immediately; work continues in the background"
                  >
                    <input
                      id="task-async-queue"
                      type="checkbox"
                      checked={asyncMode}
                      onChange={(e) => setAsyncMode(e.target.checked)}
                      aria-label="Run in background queue"
                    />
                    Run in background
                  </label>
                  <label
                    className={`muted switch-label${
                      openClaw?.delegate?.enabled === true ? "" : " disabled"
                    }`}
                    htmlFor="task-openclaw-delegate"
                    title={
                      openClaw?.delegate?.enabled === true
                        ? "POST execution to an external OpenClaw-compatible HTTP bridge; the bridge must call back with HMAC (see Safety tab)."
                        : "Enable CLAWAGORA_OPENCLAW_DELEGATE_ENABLED=1 and set CLAWAGORA_OPENCLAW_DELEGATE_URL on the server."
                    }
                  >
                    <input
                      id="task-openclaw-delegate"
                      type="checkbox"
                      checked={delegateOpenClaw}
                      onChange={(e) => setDelegateOpenClaw(e.target.checked)}
                      disabled={openClaw?.delegate?.enabled !== true}
                      aria-label="Route execution to OpenClaw HTTP bridge when enabled on server"
                    />
                    OpenClaw delegate
                  </label>
                  {delegateOpenClaw && openClaw?.delegate?.enabled === true && (
                    <input
                      id="task-openclaw-agents"
                      className="input-sm"
                      style={{ minWidth: 200, flex: "1 1 160px" }}
                      placeholder="Agents (comma-separated, optional)"
                      value={openclawAgentsStr}
                      onChange={(e) => setOpenclawAgentsStr(e.target.value)}
                      aria-label="OpenClaw agent identifiers"
                    />
                  )}
                  <span className="muted hint" aria-hidden="true">
                    ⌘↵ run
                  </span>
                  <span className="visually-hidden">
                    Shortcut: Command or Control plus Enter sends the request.
                  </span>
                  </div>
                  <div className="task-context-fields" role="group" aria-label="Shared context for bridges (optional)">
                    <p className="field-hint-muted task-context-hint">
                      Optional — for integrations: repeat the same IDs so an external bridge can load memory or group
                      related work. (Technical: <span className="mono">metadata.clawagora_context</span> / delegate{" "}
                      <span className="mono">context</span>.)
                    </p>
                    <div className="task-context-grid">
                      <label className="task-context-label">
                        Session ID
                        <input
                          id="task-context-session"
                          className="input-sm task-context-input"
                          value={contextSessionId}
                          onChange={(e) => setContextSessionId(e.target.value)}
                          placeholder="e.g. workspace-42"
                          autoComplete="off"
                          disabled={busy}
                        />
                      </label>
                      <label className="task-context-label">
                        Correlation ID
                        <input
                          id="task-context-correlation"
                          className="input-sm task-context-input"
                          value={contextCorrelationId}
                          onChange={(e) => setContextCorrelationId(e.target.value)}
                          placeholder="trace or ticket id"
                          autoComplete="off"
                          disabled={busy}
                        />
                      </label>
                      <label className="task-context-label task-context-label--wide">
                        Memory refs (comma-separated)
                        <input
                          id="task-context-memory-refs"
                          className="input-sm task-context-input"
                          value={contextMemoryRefsStr}
                          onChange={(e) => setContextMemoryRefsStr(e.target.value)}
                          placeholder="kb:doc-1, vector:abc…"
                          autoComplete="off"
                          disabled={busy}
                        />
                      </label>
                    </div>
                  </div>
                </div>
              </details>
            </div>
          </fieldset>

          {err && (
            <div className="panel panel-err" role="alert">
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
            <div className="empty-state empty-state--friendly" role="status">
              <div className="empty-icon" aria-hidden="true">
                ◎
              </div>
              <div className="empty-title">No run selected</div>
              <div className="empty-body">
                Write a <strong>clear goal</strong> above, press <strong>Send request</strong>, then follow{" "}
                <strong>Progress</strong> and the <strong>Outcome</strong> here. Successful runs include a{" "}
                <strong>receipt</strong> for audit. Reopen any item from <strong>Review</strong> on the right.
              </div>
              {!onboardingVisible ? (
                <p className="empty-state-help muted">
                  <a href="#optional-help" className="empty-state-help-link">
                    Quick reference
                  </a>{" "}
                  (terms and map) is below the workspace.
                </p>
              ) : null}
            </div>
          )}

          {task && (
            <div className="panel" aria-labelledby="task-result-heading">
              <h2 id="task-result-heading" className="panel-section-heading">
                Outcome
              </h2>
              <p className="panel-section-sub muted">
                Agent output and trace for this run — compare against the goal you stated above. Manage retries and
                approvals from <strong>Review</strong> or here.
              </p>
              <div className="task-meta row task-meta-with-actions" style={{ marginBottom: 10 }}>
                <span className="pill mono" title={task.id}>
                  {task.id.slice(0, 8)}
                </span>
                <button
                  type="button"
                  className="btn-sm task-id-copy-btn"
                  onClick={() => copyTaskIdToClipboard(task.id)}
                  aria-label="Copy full task ID to clipboard"
                >
                  {taskIdCopyFeedback ? "Copied" : "Copy ID"}
                </button>
                <span className={`risk-badge risk-${task.risk_tier}`} title={riskTierLabel(task.risk_tier)}>
                  {riskTierLabel(task.risk_tier)}
                </span>
                {cf && (
                  <span className="muted">
                    {cf.label} · {confPct}%
                  </span>
                )}
                {task.error_code && (
                  <span className="pill pill-err">{task.error_code}</span>
                )}
              </div>

              <TaskContextStrip task={task} />

              <OpenClawTaskStrip task={task} openClaw={openClaw} />

              {task.receipt && <ReceiptPanel receipt={task.receipt} />}

              {timelineLoadError ? (
                <div
                  className="timeline-load-banner"
                  role="status"
                  aria-live="polite"
                >
                  <span className="timeline-load-banner-text">
                    Timeline could not be loaded: {timelineLoadError}
                  </span>
                  <button
                    type="button"
                    className="btn-sm timeline-load-retry"
                    onClick={() => void applyTimelineForTask(task.id)}
                  >
                    Retry timeline
                  </button>
                </div>
              ) : null}

              <TaskTimeline events={events} />
            </div>
          )}
        </main>

        {/* ── Right: task list + policies ──────────────────────────────── */}
        <aside
          id="workspace-sidebar"
          className="col-secondary"
          aria-label="Workspace: history, rules, and safety"
          tabIndex={-1}
        >
          <nav className="workspace-nav" aria-labelledby="workspace-nav-heading">
            <h2 id="workspace-nav-heading" className="visually-hidden">
              Workspace sections
            </h2>
            <div
              className="tab-bar"
              role="tablist"
              aria-labelledby="workspace-nav-heading"
              onKeyDown={onWorkspaceTabKeyDown}
            >
              <button
                type="button"
                id={TAB_BUTTON_ID.tasks}
                role="tab"
                aria-selected={rightTab === "tasks"}
                aria-controls={TAB_PANEL_ID.tasks}
                tabIndex={rightTab === "tasks" ? 0 : -1}
                className={`tab${rightTab === "tasks" ? " active" : ""}`}
                onClick={() => selectWorkspaceTab("tasks")}
              >
                <span className="tab-label">Review</span>
                <span className="tab-desc">Queue and history</span>
              </button>
              <button
                type="button"
                id={TAB_BUTTON_ID.policies}
                role="tab"
                aria-selected={rightTab === "policies"}
                aria-controls={TAB_PANEL_ID.policies}
                tabIndex={rightTab === "policies" ? 0 : -1}
                className={`tab${rightTab === "policies" ? " active" : ""}`}
                onClick={() => selectWorkspaceTab("policies")}
              >
                <span className="tab-label">Rules</span>
                <span className="tab-desc">Allow / block</span>
              </button>
              <button
                type="button"
                id={TAB_BUTTON_ID.governance}
                role="tab"
                aria-selected={rightTab === "governance"}
                aria-controls={TAB_PANEL_ID.governance}
                tabIndex={rightTab === "governance" ? 0 : -1}
                className={`tab${rightTab === "governance" ? " active" : ""}`}
                onClick={() => selectWorkspaceTab("governance")}
              >
                <span className="tab-label">Safety</span>
                <span className="tab-desc">Strictness and health</span>
              </button>
            </div>
          </nav>

          <div className="right-column-scroll">
          <div
            className="task-list"
            id={TAB_PANEL_ID.tasks}
            role="tabpanel"
            aria-labelledby={TAB_BUTTON_ID.tasks}
            aria-label="Review: task list, search, and filters"
            hidden={rightTab !== "tasks"}
          >
              <p className="task-list-intro muted">
                Search matches goal text; filters narrow by status. Select a row to load full detail, timeline, and
                receipt on the left. List refreshes while runs are active.
              </p>
              <div className="task-list-toolbar">
                <div className="task-list-toolbar-row">
                  <label className="visually-hidden" htmlFor={taskSearchFieldId}>
                    Search tasks by goal text
                  </label>
                  <input
                    id={taskSearchFieldId}
                    type="search"
                    className="task-list-search"
                    placeholder="Search goal text…"
                    value={taskSearchInput}
                    onChange={(e) => setTaskSearchInput(e.target.value)}
                    autoComplete="off"
                    enterKeyHint="search"
                  />
                  <button
                    type="button"
                    className="btn-sm task-list-refresh-btn"
                    onClick={() => void refreshTaskList()}
                    aria-label="Refresh task list"
                  >
                    Refresh
                  </button>
                </div>
                <p className="task-list-count muted" role="status" aria-live="polite">
                  {taskListLoadError ? (
                    "List unavailable"
                  ) : taskListCount !== null ? (
                    <>
                      <strong>{taskListCount}</strong> task{taskListCount === 1 ? "" : "s"}
                      {taskListCount > taskList.length ? (
                        <>
                          {" "}
                          (showing first {taskList.length})
                        </>
                      ) : null}
                      {taskSearchQuery ? (
                        <>
                          {" "}
                          matching &quot;{taskSearchQuery}&quot;
                        </>
                      ) : null}
                    </>
                  ) : (
                    `${taskList.length} loaded`
                  )}
                </p>
              </div>
              {taskListLoadError ? (
                <div
                  className="timeline-load-banner workspace-fetch-banner"
                  role="status"
                  aria-live="polite"
                >
                  <span className="timeline-load-banner-text">
                    Task list could not be loaded: {taskListLoadError}
                  </span>
                  <button
                    type="button"
                    className="btn-sm timeline-load-retry"
                    onClick={() => void refreshTaskList()}
                  >
                    Retry
                  </button>
                </div>
              ) : null}
              <div className="task-filter-row" role="toolbar" aria-label="Filter tasks by status">
                {(["all", "judicial", "needs_revision"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={`chip${taskListFilter === f ? " chip-active" : ""}`}
                    aria-pressed={taskListFilter === f}
                    aria-label={
                      f === "all"
                        ? "Show all tasks in the list"
                        : f === "judicial"
                          ? "Show only tasks waiting for human approval"
                          : "Show only tasks that need revision"
                    }
                    onClick={() => setTaskListFilter(f)}
                  >
                    {f === "all" ? "All" : f === "judicial" ? "Needs approval" : "Needs fix"}
                  </button>
                ))}
              </div>
              {taskList.length === 0 && !taskListLoadError && (
                <div className="muted task-list-empty" style={{ padding: "10px 12px" }}>
                  {taskSearchQuery ? (
                    <>
                      No tasks match your search. Try different words or{" "}
                      <button type="button" className="link-inline" onClick={() => setTaskSearchInput("")}>
                        clear search
                      </button>
                      .
                    </>
                  ) : taskListFilter === "all" ? (
                    <>
                      No tasks yet — press <strong>Send request</strong> on the left to create one. This list updates
                      automatically when runs finish or need you.
                    </>
                  ) : (
                    <>
                      No tasks in this filter — switch to <strong>All</strong> or send a new request from the left.
                    </>
                  )}
                </div>
              )}
              {taskList.map((t) => {
                const preview =
                  (t.input_text ?? "").length > 55
                    ? (t.input_text ?? "").slice(0, 55) + "…"
                    : (t.input_text ?? "—");
                const rowLoading = loadingTaskId === t.id;
                return (
                <div
                  key={t.id}
                  className={`task-item${task?.id === t.id ? " active" : ""}${rowLoading ? " loading" : ""}`}
                  onClick={() => void loadTask(t.id)}
                  role="button"
                  tabIndex={0}
                  aria-current={task?.id === t.id ? "true" : undefined}
                  aria-busy={rowLoading}
                  aria-label={`Open request: ${preview}. Status: ${taskStatusLabel(t.status)}. ${riskTierLabel(t.risk_tier)}.`}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      void loadTask(t.id);
                    }
                  }}
                >
                  <div className="row" style={{ gap: 6 }}>
                    <span
                      className={`status-dot status-dot-${t.status}`}
                      title={taskStatusLabel(t.status)}
                      aria-hidden="true"
                    />
                    <span className="task-item-text">{preview}</span>
                    {rowLoading ? (
                      <span className="visually-hidden">Loading request details</span>
                    ) : null}
                  </div>
                  <div className="task-item-meta">
                    <span className="task-item-id mono muted" title={t.id}>
                      {t.id.slice(0, 8)}
                    </span>
                    <span className="muted" style={{ fontSize: 10 }}>
                      {t.created_at.slice(0, 16).replace("T", " ")}
                    </span>
                    <span className={`risk-badge risk-${t.risk_tier}`} title={riskTierLabel(t.risk_tier)}>
                      {riskTierLabel(t.risk_tier)}
                    </span>
                    {t.error_code && (
                      <span className="pill pill-err pill-sm">{t.error_code}</span>
                    )}
                  </div>
                </div>
              );
              })}
            </div>

          <div
            className="policy-panel"
            id={TAB_PANEL_ID.policies}
            role="tabpanel"
            aria-labelledby={TAB_BUTTON_ID.policies}
            hidden={rightTab !== "policies"}
          >
              <p className="policy-tab-intro muted">
                Optional. Each row has <strong>Turn on</strong>, <strong>Turn off</strong>, <strong>Edit</strong>, and{" "}
                <strong>Remove</strong>. Only one set can be on at a time. Regex and expert JSON sit under{" "}
                <strong>Advanced settings</strong> in the form below.
              </p>
              {policyFeedback ? (
                <div
                  className={`policy-feedback policy-feedback--${policyFeedback.kind}`}
                  role={policyFeedback.kind === "error" ? "alert" : "status"}
                  aria-live={policyFeedback.kind === "error" ? "assertive" : "polite"}
                >
                  {policyFeedback.message}
                </div>
              ) : null}
              {policyListLoadError ? (
                <div
                  className="timeline-load-banner workspace-fetch-banner"
                  role="status"
                  aria-live="polite"
                >
                  <span className="timeline-load-banner-text">
                    Rules list could not be loaded: {policyListLoadError}
                  </span>
                  <button
                    type="button"
                    className="btn-sm timeline-load-retry"
                    onClick={() => void refreshPolicies()}
                  >
                    Retry
                  </button>
                </div>
              ) : null}
              <div className="policy-list">
                <p id="policy-row-actions-hint" className="policy-list-ux-hint muted">
                  <strong>Turn on</strong> applies that draft to new tasks (only one set can be active).{" "}
                  <strong>Turn off</strong> clears the active set. <strong>Edit</strong> loads the draft into the form
                  below. <strong>Remove</strong> deletes the draft from the list.
                </p>
                {policies.length === 0 && (
                  <div className="muted" style={{ padding: "10px 12px" }}>
                    No drafts yet — add one with the form at the bottom of this tab.
                  </div>
                )}
                {policyLogLoadError ? (
                  <div
                    className="timeline-load-banner workspace-fetch-banner"
                    role="status"
                    aria-live="polite"
                  >
                    <span className="timeline-load-banner-text">
                      Rule change log could not be loaded: {policyLogLoadError}
                    </span>
                    <button
                      type="button"
                      className="btn-sm timeline-load-retry"
                      onClick={() => void refreshPolicyLog()}
                    >
                      Retry
                    </button>
                  </div>
                ) : null}
                {policyLog.length > 0 ? (
                  <details className="policy-log-disclosure">
                    <summary className="policy-log-disclosure-summary disclosure-summary-a11y">Rule change log</summary>
                    <div className="muted policy-log-scroll policy-log-disclosure-body" style={{ fontSize: 10 }}>
                      {policyLog.slice(0, 12).map((e) => (
                        <div key={e.id} style={{ marginBottom: 4 }}>
                          {e.created_at.slice(0, 16).replace("T", " ")} · {e.action}
                          {e.policy_draft_id ? ` · ${String(e.policy_draft_id).slice(0, 8)}` : ""}
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
                {policies.map((p) => {
                  const rowLabelId = `policy-draft-label-${p.id}`;
                  return (
                    <div
                      key={p.id}
                      className={`policy-item${p.is_active ? " policy-active" : ""}${
                        editingPolicyId === p.id ? " policy-item-editing" : ""
                      }`}
                      role="group"
                      aria-labelledby={rowLabelId}
                    >
                      <div className="policy-item-left">
                        {p.is_active ? (
                          <span className="policy-active-dot" aria-hidden="true" title="Active" />
                        ) : null}
                        <span id={rowLabelId} className="policy-name">
                          {p.name}
                        </span>
                        {p.is_active ? (
                          <span className="policy-active-label policy-active-label-static" aria-hidden="true">
                            On
                          </span>
                        ) : null}
                        {isSeedPolicyDraft(p) ? (
                          <span className="pill pill-sm" title="Created by initial migration; safe to delete">
                            seed
                          </span>
                        ) : null}
                      </div>
                      <div className="policy-item-right">
                        <div
                          className="policy-item-actions"
                          role="toolbar"
                          aria-label={`Actions for rule set ${p.name}`}
                        >
                          {p.is_active ? (
                            <button
                              type="button"
                              className="btn-sm btn-deactivate policy-row-toggle"
                              aria-describedby="policy-row-actions-hint"
                              onClick={() => void handleTurnOffActivePolicy()}
                            >
                              Turn off
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="btn-activate policy-row-toggle"
                              aria-describedby="policy-row-actions-hint"
                              onClick={() => void handleActivatePolicy(p.id)}
                            >
                              Turn on
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn-sm policy-row-edit"
                            aria-describedby="policy-row-actions-hint"
                            onClick={() => beginEditPolicy(p)}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="btn-sm policy-row-remove"
                            title="Remove this draft from the list"
                            aria-describedby="policy-row-actions-hint"
                            onClick={() => void handleDeletePolicy(p.id)}
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <details className="policy-proposals-disclosure">
                <summary className="policy-proposals-disclosure-summary disclosure-summary-a11y">
                  Suggested rule changes (optional)
                </summary>
                <PolicyProposalsPanel
                  compact
                  onPoliciesMayHaveChanged={() => void refreshPolicies()}
                />
              </details>

              <div ref={policyFormSectionRef} className="policy-form-anchor">
                <PolicyLegislativeForm
                  key={editingPolicyId ?? "create"}
                  policyName={policyName}
                  onPolicyNameChange={setPolicyName}
                  form={policyLegislativeForm}
                  onFormChange={setPolicyLegislativeForm}
                  executorOptions={mergedExecutorOptions}
                  executorSource={
                    policyExecutorsApi !== null && policyExecutorsApi.length > 0 ? "server" : "fallback"
                  }
                  error={policyErr}
                  onSubmit={() => void handleSavePolicy()}
                  submitDisabled={!policyName.trim()}
                  initialAdvancedOpen={policyFormInitialAdvancedOpen}
                  formMode={editingPolicyId ? "edit" : "create"}
                  onCancelEdit={editingPolicyId ? cancelPolicyEdit : undefined}
                />
              </div>
            </div>

            <div
              id={TAB_PANEL_ID.governance}
              role="tabpanel"
              aria-labelledby={TAB_BUTTON_ID.governance}
              hidden={rightTab !== "governance"}
            >
              <GovernancePanel
                profiles={govProfiles}
                dashboard={govDashboard}
                summary={govSummary}
                summaryFailed={govSummaryFailed}
                summaryRetrying={govSummaryRetrying}
                governanceRefreshing={govRefreshing}
                onRefreshGovernance={() => void refreshGovernance()}
                openClaw={openClaw}
                busy={govLevelBusy}
                onSetLevel={handleSetLevel}
              />
            </div>
          </div>
        </aside>
      </div>

      {!onboardingVisible ? (
        <OptionalProductHelp
          onReplayTour={() => {
            resetOnboardingDismissal();
            setOnboardingVisible(true);
          }}
        />
      ) : null}
    </div>
  );
}

function TaskContextStrip({ task }: { task: TaskRecord }) {
  const contextTitleId = useId();
  const raw = task.metadata?.clawagora_context;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const ctx = raw as Record<string, unknown>;
  const sessionId = typeof ctx.session_id === "string" ? ctx.session_id.trim() : "";
  const correlationId = typeof ctx.correlation_id === "string" ? ctx.correlation_id.trim() : "";
  const memoryRefs = Array.isArray(ctx.memory_refs)
    ? ctx.memory_refs.filter((x): x is string => typeof x === "string").map((s) => s.trim()).filter(Boolean)
    : [];
  if (!sessionId && !correlationId && memoryRefs.length === 0) return null;

  return (
    <section className="task-context-strip" aria-labelledby={contextTitleId}>
      <h3 id={contextTitleId} className="task-context-strip-title">
        Shared context (stored on this task)
      </h3>
      <p className="task-context-strip-lead muted">
        Sent to bridges as <span className="mono">metadata.clawagora_context</span> and as delegate{" "}
        <span className="mono">context</span> when OpenClaw delegate runs.
      </p>
      <dl className="task-context-strip-dl">
        {sessionId ? (
          <>
            <dt>Session ID</dt>
            <dd className="mono">{sessionId}</dd>
          </>
        ) : null}
        {correlationId ? (
          <>
            <dt>Correlation ID</dt>
            <dd className="mono">{correlationId}</dd>
          </>
        ) : null}
        {memoryRefs.length > 0 ? (
          <>
            <dt>Memory refs</dt>
            <dd className="mono">{memoryRefs.join(", ")}</dd>
          </>
        ) : null}
      </dl>
    </section>
  );
}

function OpenClawTaskStrip({
  task,
  openClaw,
}: {
  task: TaskRecord;
  openClaw: OpenClawStatus | null;
}) {
  const openClawTitleId = useId();
  const oc = task.metadata?.openclaw;
  if (!oc || typeof oc !== "object" || oc === null) return null;
  const raw = oc as {
    delegate?: boolean;
    phase?: string;
    agents?: unknown;
    callback_schema?: string;
    artifacts?: unknown;
  };
  const phase = raw.phase ?? "";
  const agents = Array.isArray(raw.agents) ? raw.agents.map((a) => String(a)) : [];
  const artifacts = Array.isArray(raw.artifacts)
    ? raw.artifacts.filter(
        (x): x is {
          role?: string;
          content?: string;
          agent_id?: string;
          meta?: unknown;
        } => x !== null && typeof x === "object",
      )
    : [];
  if (!raw.delegate && !phase) return null;

  const schemaStr = typeof raw.callback_schema === "string" ? raw.callback_schema.trim() : "";

  return (
    <section className="openclaw-strip openclaw-strip-panel" aria-labelledby={openClawTitleId}>
      <h3 id={openClawTitleId} className="openclaw-strip-title">
        OpenClaw
      </h3>
      {raw.delegate ? (
        <p className="openclaw-strip-lede muted">
          Runs on an external HTTP bridge. The signed callback can carry structured{" "}
          <strong>artifacts</strong> (e.g. proposal, critique)—mirrored here and in the receipt.
        </p>
      ) : null}
      {schemaStr ? (
        <div className="gov-stat-row openclaw-stat-compact">
          <span className="gov-stat-label">Schema</span>
          <span className="gov-stat-value mono openclaw-schema-value" title={schemaStr}>
            {schemaStr}
          </span>
        </div>
      ) : null}
      {phase ? (
        <div className="gov-stat-row openclaw-stat-compact">
          <span className="gov-stat-label">Phase</span>
          <span className="gov-stat-value">{phase.replace(/_/g, " ")}</span>
        </div>
      ) : null}
      {agents.length > 0 ? (
        <div className="gov-stat-row openclaw-stat-compact">
          <span className="gov-stat-label">Agents</span>
          <span className="gov-stat-value mono openclaw-agents-value" title={agents.join(", ")}>
            {agents.join(", ")}
          </span>
        </div>
      ) : null}
      <OpenClawArtifactsList items={artifacts} variant="strip" title="Agent lanes" />
      {phase === "awaiting_callback" && openClaw?.delegate?.callback_url ? (
        <p className="openclaw-wait-hint muted">
          Awaiting signed callback (HMAC) to{" "}
          <span className="mono openclaw-callback-url" title={openClaw.delegate.callback_url}>
            {openClaw.delegate.callback_url}
          </span>
        </p>
      ) : null}
    </section>
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
  summary,
  summaryFailed,
  summaryRetrying,
  governanceRefreshing,
  onRefreshGovernance,
  openClaw,
  busy,
  onSetLevel,
}: {
  profiles: GovernanceProfiles | null;
  dashboard: GovernanceDashboard | null;
  summary: GovernanceSummary | null;
  summaryFailed: boolean;
  summaryRetrying: boolean;
  governanceRefreshing: boolean;
  onRefreshGovernance: () => void;
  openClaw: OpenClawStatus | null;
  busy: boolean;
  onSetLevel: (level: "minimal" | "balanced" | "strict") => void;
}) {
  const [copiedCallback, setCopiedCallback] = useState(false);
  const [registryOpen, setRegistryOpen] = useState(() => loadPromptRegistryOpen());
  const currentLevel = profiles?.selected_level ?? dashboard?.governance_level ?? "balanced";
  const alertCount = dashboard?.alerts?.length ?? 0;
  const deleg = openClaw?.delegate;
  const cb = summary?.prompts.circuit_breaker;
  const showOpsLoading = governanceRefreshing && !summary && !summaryFailed;
  const showOpsIdle =
    !summary && !summaryFailed && !governanceRefreshing && !showOpsLoading;
  const delegateDetailBelow = Boolean(deleg);
  const registryKeys = summary?.prompts.registry_keys ?? [];
  const registryForcedCount = registryKeys.filter(
    (k) => k.circuit_forced_version != null && String(k.circuit_forced_version).trim() !== "",
  ).length;

  return (
    <div className="gov-panel">
      <p className="gov-panel-intro muted">
        Defaults are fine. This column aligns <strong>how strictly</strong> agents may operate with your org&apos;s goals:
        health snapshots and oversight — separate from the <strong>goal text</strong> on the left or <strong>Rules</strong>{" "}
        drafts.
      </p>
      <section
        className="gov-ops-section"
        aria-labelledby="gov-ops-heading"
        aria-busy={governanceRefreshing}
      >
          <div className="gov-ops-header">
            <h2 id="gov-ops-heading" className="gov-section-title">
              Status snapshot
            </h2>
            <button
              type="button"
              className="btn-sm gov-refresh-btn"
              onClick={onRefreshGovernance}
              disabled={governanceRefreshing}
              aria-busy={governanceRefreshing}
              aria-label={
                governanceRefreshing ? "Refreshing safety snapshot" : "Refresh safety snapshot"
              }
            >
              {governanceRefreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {showOpsLoading ? (
            <div className="gov-ops-loading" role="status" aria-live="polite">
              <span className="gov-ops-loading-spinner" aria-hidden />
              <span>Loading safety snapshot…</span>
            </div>
          ) : null}

          {showOpsIdle ? (
            <p className="gov-ops-idle muted" role="status">
              Snapshot not loaded. Press Refresh.
            </p>
          ) : null}

          {summaryFailed ? (
            <div
              className="gov-summary-unavailable"
              role={summary ? "status" : "alert"}
              aria-live={summaryRetrying ? "polite" : "assertive"}
            >
              {summary
                ? "Could not refresh the snapshot; showing last successful data."
                : "Safety snapshot unavailable (network or server error)."}
              {summaryRetrying ? <div className="gov-summary-retry-line">Retrying summary…</div> : null}
            </div>
          ) : null}

          {summary ? (
            <div className={governanceRefreshing ? "gov-ops-content gov-ops-content-dim" : "gov-ops-content"}>
              <p
                className="gov-summary-meta"
                title="Snapshot schema and app version (read-only)"
              >
                {summary.schema} · v{summary.version}
              </p>

              <div className="gov-stat-row">
                <span className="gov-stat-label">Policy</span>
                <span className="gov-stat-value gov-stat-value-wrap">
                  {summary.policy.has_active_policy
                    ? summary.policy.active_policy_name ?? summary.policy.active_policy_id ?? "active"
                    : "none active"}
                  {" · "}
                  drafts {summary.policy.draft_count}
                </span>
              </div>

              <div className="gov-stat-row">
                <span className="gov-stat-label">Capabilities</span>
                <span className="gov-stat-value gov-stat-value-wrap">
                  sha256 {summary.capabilities.require_sha256 ? "required" : "off"} · source URL{" "}
                  {summary.capabilities.require_source_url ? "required" : "off"} · bundles{" "}
                  {summary.capabilities.active_bundle_count}/{summary.capabilities.total_bundle_count}
                </span>
              </div>
              {summary.capabilities.offender_count > 0 ? (
                <div className="gov-stat-row" style={{ alignItems: "flex-start" }}>
                  <span className="gov-stat-label">Offenders</span>
                  <span className="gov-stat-value gov-stat-value-wrap">
                    <span className={`gov-pill${summary.capabilities.offender_count > 0 ? " gov-pill-warn" : ""}`}>
                      {summary.capabilities.offender_count}
                    </span>
                  </span>
                </div>
              ) : (
                <div className="gov-stat-row">
                  <span className="gov-stat-label">Offenders</span>
                  <span className="gov-stat-value">
                    <span className="gov-pill gov-pill-ok">none</span>
                  </span>
                </div>
              )}
              {summary.capabilities.offenders.length > 0 ? (
                <div className="gov-offender-list mono" role="list">
                  {summary.capabilities.offenders.map((o) => (
                    <div key={o.id} role="listitem">
                      {o.slug}: {o.reasons.join(", ")}
                    </div>
                  ))}
                </div>
              ) : null}

              <details className="gov-tech-disclosure">
                <summary className="gov-tech-disclosure-summary disclosure-summary-a11y">
                  Technical: prompt circuit, registry, OpenClaw summary
                </summary>
                <div className="gov-tech-disclosure-body">
                  {cb ? (
                    <>
                      <div className="gov-stat-row" style={{ marginTop: 6 }}>
                        <span className="gov-stat-label">Prompt circuit</span>
                        <span className="gov-stat-value gov-stat-value-wrap">
                          <span className={`gov-pill${cb.enabled ? " gov-pill-on" : " gov-pill-off"}`}>
                            {cb.enabled ? "on" : "off"}
                          </span>
                          <span className="gov-inline-meta">
                            {" "}
                            · samples ≥{cb.min_samples} · err ≤{(cb.error_rate_max * 100).toFixed(0)}% · cost ≤ $
                            {cb.avg_cost_usd_max.toFixed(4)} · fallback {cb.fallback_version_default}
                          </span>
                        </span>
                      </div>
                      <div className="gov-stat-row">
                        <span className="gov-stat-label">Circuit cache</span>
                        <span className="gov-stat-value gov-stat-value-wrap">
                          TTL {cb.metrics_ttl_seconds}s · cooldown {cb.cooldown_seconds}s
                        </span>
                      </div>
                    </>
                  ) : null}

                  <div className="gov-registry-block">
                    <button
                      type="button"
                      className="gov-registry-toggle"
                      id="gov-prompt-registry-toggle"
                      onClick={() => {
                        setRegistryOpen((o) => {
                          const next = !o;
                          savePromptRegistryOpen(next);
                          return next;
                        });
                      }}
                      aria-expanded={registryOpen}
                      aria-controls="gov-prompt-registry-panel"
                    >
                      <span className="gov-registry-chevron" aria-hidden>
                        {registryOpen ? "▼" : "▶"}
                      </span>
                      <span className="gov-registry-toggle-label">Prompt registry</span>
                      <span className="gov-registry-toggle-meta muted">
                        {registryKeys.length} keys · {registryForcedCount} forced
                      </span>
                    </button>
                    {registryOpen ? (
                      <div
                        id="gov-prompt-registry-panel"
                        role="region"
                        aria-labelledby="gov-prompt-registry-toggle"
                        className="gov-prompt-registry"
                      >
                        {registryKeys.length === 0 ? (
                          <div className="gov-registry-empty muted">No prompt keys in registry.</div>
                        ) : (
                          registryKeys.map((k) => (
                            <div key={k.prompt_key} className="gov-prompt-registry-row">
                              <span className="mono">{k.prompt_key}</span>
                              <span className="muted">
                                forced {k.circuit_forced_version ?? "—"} ·{" "}
                                {k.versions.map((v) => `${v.version}:${v.rollout}%`).join(" · ")}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    ) : null}
                  </div>

                  {!delegateDetailBelow ? (
                    <div className="gov-stat-row" style={{ marginTop: 8 }}>
                      <span className="gov-stat-label">OpenClaw delegate</span>
                      <span className="gov-stat-value gov-stat-value-wrap">
                        {summary.integrations.openclaw_delegate.enabled ? "on" : "off"} · URL{" "}
                        {summary.integrations.openclaw_delegate.url_configured ? "ok" : "missing"} · cache{" "}
                        {summary.integrations.openclaw_delegate.callback_guard_cache_backend ?? "—"}
                      </span>
                    </div>
                  ) : null}
                </div>
              </details>

              {delegateDetailBelow ? (
                <p className="gov-cross-ref muted">OpenClaw delegate details are in OpenClaw gateway below.</p>
              ) : null}
            </div>
          ) : null}
        </section>

        <details className="gov-quorum-disclosure">
          <summary className="gov-quorum-disclosure-summary disclosure-summary-a11y">
            Human approvals and env presets
          </summary>
          <div className="gov-quorum-disclosure-body">
            <JudicialQuorumCard />
          </div>
        </details>

        <section aria-labelledby="gov-level-heading">
        <h2
          id="gov-level-heading"
          className="gov-section-title"
          style={{ marginTop: 14 }}
        >
          How strict should checks be?
        </h2>
        <div className="gov-help">
          Higher = more validation and human review before work completes. Pick one level for this profile.
        </div>
        <div className="gov-levels" aria-labelledby="gov-level-heading">
        {(["minimal", "balanced", "strict"] as const).map((lvl) => {
          const meta = LEVEL_DESC[lvl];
          const card = profiles?.cards?.find((c) => c.level === lvl);
          const selected = currentLevel === lvl;
          return (
            <button
              key={lvl}
              type="button"
              className={`gov-level-card${selected ? " selected" : ""}`}
              style={selected ? { borderColor: meta.color } : undefined}
              disabled={busy || selected}
              onClick={() => onSetLevel(lvl)}
              aria-current={selected ? "true" : undefined}
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
      </section>

      {openClaw && (
        <section className="gov-openclaw-section" aria-labelledby="gov-openclaw-heading">
          <h2 id="gov-openclaw-heading" className="gov-section-title" style={{ marginTop: 14 }}>
            OpenClaw gateway
          </h2>
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

          {deleg ? (
            <details className="gov-openclaw-delegate-disclosure">
              <summary className="gov-openclaw-delegate-summary disclosure-summary-a11y">
                Delegate bridge (agents and callback)
              </summary>
              <div className="gov-openclaw-delegate-body">
                <div className="gov-help" style={{ marginBottom: 8 }}>
                  Server-side flags route approved work to an HTTP bridge; the bridge runs your OpenClaw agents and
                  POSTs back with <span className="mono">X-ClawAgora-Signature</span>.
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
                {deleg.knowledge ? (
                  <div className="gov-stat-row">
                    <span className="gov-stat-label">Knowledge pins</span>
                    <span className="gov-stat-value">
                      sha256: {deleg.knowledge.capability_require_sha256 ? "required" : "optional"}
                      {" · "}
                      source URL: {deleg.knowledge.capability_require_source_url ? "required" : "optional"}
                    </span>
                  </div>
                ) : null}
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
                    Set <span className="mono">CLAWAGORA_PUBLIC_BASE_URL</span> so delegate payloads include a callback
                    URL.
                  </div>
                )}
              </div>
            </details>
          ) : null}
        </section>
      )}

      {dashboard && (
        <section aria-labelledby="gov-system-heading">
            <h2 id="gov-system-heading" className="gov-section-title" style={{ marginTop: 14 }}>
            Server health
          </h2>
          <div className="gov-stat-row">
            <span className="gov-stat-label">Profile</span>
            <span className="gov-stat-value">{dashboard.profile}</span>
          </div>
          <div className="gov-stat-row">
            <span className="gov-stat-label">Daily budget</span>
            <span className="gov-stat-value">{(dashboard.daily_budget * 100).toFixed(0)}%</span>
          </div>
          {dashboard.tasks_scanned != null ? (
            <div className="gov-stat-row">
              <span className="gov-stat-label">Tasks scanned</span>
              <span className="gov-stat-value">{dashboard.tasks_scanned}</span>
            </div>
          ) : null}
          <div className="gov-stat-row">
            <span className="gov-stat-label">Alerts</span>
            <span className={`gov-stat-value${alertCount > 0 ? " gov-alert" : ""}`}>
              {alertCount === 0 ? "none" : alertCount}
            </span>
          </div>
        </section>
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
  const panelId = useId();
  const voterFieldId = `${panelId}-voter`;
  const noteFieldId = `${panelId}-note`;
  return (
    <div className="panel approval-panel" role="region" aria-label="Human approval">
      <div className="row" style={{ marginBottom: 6, gap: 8 }}>
        <span className={`risk-badge risk-${ar.risk_tier}`} title={riskTierLabel(ar.risk_tier)}>
          {riskTierLabel(ar.risk_tier)}
        </span>
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
        <label className="visually-hidden" htmlFor={voterFieldId}>
          Voter identifier
        </label>
        <input
          id={voterFieldId}
          className="input-sm"
          style={{ flex: 1 }}
          placeholder="voter id"
          value={voterId}
          onChange={(e) => onVoterIdChange(e.target.value)}
          autoComplete="username"
        />
      </div>
      <label className="visually-hidden" htmlFor={noteFieldId}>
        Optional note
      </label>
      <textarea
        id={noteFieldId}
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
          aria-busy={busy}
          onClick={() => onVote("approve")}
        >
          Approve
        </button>
        <button
          type="button"
          className="btn-reject"
          disabled={busy || !voterId.trim()}
          aria-busy={busy}
          onClick={() => onVote("reject")}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

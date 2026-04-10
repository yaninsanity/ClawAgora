import type { TimelineEvent } from "../api/client";

function firstValidationIssueDetail(payload: Record<string, unknown>): string {
  const issues = payload.issues;
  if (!Array.isArray(issues) || issues.length === 0) return "";
  const first = issues[0] as { code?: string; message?: string };
  const code = String(first.code ?? "").trim();
  const msg = String(first.message ?? "").trim();
  if (code && msg) return `${code}: ${msg}`;
  return code || msg || "";
}

function summarize(ev: TimelineEvent): string {
  if (ev.kind === "envelope") {
    const rid = String(ev.payload.request_id ?? "");
    return `Intake complete (${rid.slice(0, 8)}…)`;
  }
  if (ev.phase === "classify") {
    const label = String((ev.payload as { label?: string }).label ?? "");
    const conf = (ev.payload as { confidence?: number }).confidence;
    const pct = conf != null ? ` · ${Math.round(conf * 100)}%` : "";
    return `Classified: ${label}${pct}`;
  }
  if (ev.phase === "plan") {
    const steps = Array.isArray((ev.payload as { steps?: unknown }).steps)
      ? (ev.payload as { steps: unknown[] }).steps.length
      : 0;
    return `Plan ready (${steps} steps)`;
  }
  if (ev.phase === "validate") {
    const passed = Boolean((ev.payload as { passed?: boolean }).passed);
    const detail = !passed ? firstValidationIssueDetail(ev.payload) : "";
    const short =
      detail.length > 90 ? `${detail.slice(0, 88).trimEnd()}…` : detail;
    const suffix = short ? ` — ${short}` : "";
    return `${ev.kind}: ${passed ? "✓ pass" : "✗ fail"}${suffix}`;
  }
  if (ev.phase === "execute") {
    const ex = String((ev.payload as { executor?: string }).executor ?? "");
    return `Executed ${ex}`;
  }
  if (ev.phase === "synthesize" && ev.kind === "result") {
    return "Synthesis complete";
  }
  if (ev.phase === "terminal" && ev.kind === "failed") {
    const code = String((ev.payload as { error_code?: string }).error_code ?? "");
    const st = String((ev.payload as { stage?: string }).stage ?? "");
    const et = String((ev.payload as { error_type?: string }).error_type ?? "");
    const extra = et ? ` · ${et}` : "";
    return `Failed (${code}) at ${st}${extra}`;
  }
  if (ev.phase === "terminal" && ev.kind === "completed") {
    return "Pipeline completed";
  }
  if (ev.phase === "terminal" && ev.kind === "openclaw_completed") {
    const n = Number((ev.payload as { artifact_count?: number }).artifact_count ?? 0);
    const roles = (ev.payload as { artifact_roles?: string[] }).artifact_roles ?? [];
    const roleHint = roles.length > 0 ? ` · ${roles.slice(0, 5).join(", ")}` : "";
    return n > 0 ? `OpenClaw · ${n} artifact${n === 1 ? "" : "s"}${roleHint}` : "OpenClaw · done";
  }
  if (ev.phase === "governance") {
    if (ev.kind === "accountability_feedback") {
      return "Governance · accountability snapshot (from run)";
    }
    if (ev.kind === "manual_feedback") {
      return "Governance · manual feedback";
    }
    return `Governance · ${ev.kind}`;
  }
  return `${ev.phase} · ${ev.kind}`;
}

function evStatusClass(ev: TimelineEvent): string {
  if (ev.phase === "terminal" && ev.kind === "failed") return "ev-failed";
  if (ev.phase === "terminal" && ev.kind === "completed") return "ev-completed";
  if (ev.phase === "terminal" && ev.kind === "openclaw_completed") return "ev-completed ev-openclaw";
  if (ev.phase === "governance") return "ev-governance";
  return "";
}

export function TaskTimeline(props: { events: TimelineEvent[] }) {
  const sorted = [...props.events].sort((a, b) => a.sequence - b.sequence);
  if (sorted.length === 0) return null;
  return (
    <section className="timeline" aria-label="Request progress — stages completed in order">
      <h3 className="timeline-heading">Progress</h3>
      <p className="timeline-intro muted">
        Each entry is a stage the system finished, newest at the bottom — so you can follow what happened without reading
        logs.
      </p>
      <ol className="timeline-list">
        {sorted.map((ev) => {
          const st = evStatusClass(ev);
          const summary = summarize(ev);
          const validateTitle =
            ev.phase === "validate" && !(ev.payload as { passed?: boolean }).passed
              ? firstValidationIssueDetail(ev.payload) || summary
              : undefined;
          return (
          <li
            key={`${ev.sequence}-${ev.phase}-${ev.kind}`}
            className={st ? `timeline-item ${st}` : "timeline-item"}
            title={validateTitle}
          >
            <div className="row" style={{ gap: 6, marginBottom: 2 }}>
              <span className="pill pill-sm">{ev.phase}</span>
              <span className="muted">#{ev.sequence}</span>
            </div>
            <div className="timeline-summary">{summary}</div>
          </li>
        );
        })}
      </ol>
    </section>
  );
}


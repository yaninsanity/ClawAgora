import type { TimelineEvent } from "../api/client";

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
    return `${ev.kind}: ${passed ? "✓ pass" : "✗ fail"}`;
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
  return `${ev.phase} · ${ev.kind}`;
}

function evClass(ev: TimelineEvent): string {
  if (ev.phase === "terminal" && ev.kind === "failed") return "event ev-failed";
  if (ev.phase === "terminal" && ev.kind === "completed") return "event ev-completed";
  return "event";
}

export function TaskTimeline(props: { events: TimelineEvent[] }) {
  const sorted = [...props.events].sort((a, b) => a.sequence - b.sequence);
  if (sorted.length === 0) return null;
  return (
    <div className="timeline">
      {sorted.map((ev) => (
        <div key={`${ev.sequence}-${ev.phase}-${ev.kind}`} className={evClass(ev)}>
          <div className="row" style={{ gap: 6, marginBottom: 2 }}>
            <span className="pill pill-sm">{ev.phase}</span>
            <span className="muted">#{ev.sequence}</span>
          </div>
          <div style={{ fontSize: 12 }}>{summarize(ev)}</div>
        </div>
      ))}
    </div>
  );
}


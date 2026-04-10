import { useCallback, useEffect, useState } from "react";
import {
  fetchPolicyProposals,
  resolvePolicyProposal,
  type PolicyEvolutionProposalRow,
} from "../api/client";

type Props = {
  /** Called after accept/reject so parent can refresh policy drafts. */
  onPoliciesMayHaveChanged?: () => void;
  /** Hide title block when nested under a disclosure. */
  compact?: boolean;
};

export function PolicyProposalsPanel({ onPoliciesMayHaveChanged, compact }: Props) {
  const [rows, setRows] = useState<PolicyEvolutionProposalRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("policy-from-proposal");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setErr(null);
    try {
      setRows(await fetchPolicyProposals());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, action: "accept" | "reject") => {
    setActionErr(null);
    setBusyId(id);
    try {
      await resolvePolicyProposal(id, {
        action,
        draft_name: action === "accept" ? draftName.trim() || "policy-from-proposal" : undefined,
        note: note.trim() || undefined,
      });
      await load();
      onPoliciesMayHaveChanged?.();
      setOpenId(null);
      setNote("");
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const pending = rows.filter((r) => r.status === "pending");

  if (loading) {
    return (
      <div className="policy-proposals hci-card-muted" role="status">
        Loading policy proposals…
      </div>
    );
  }

  return (
    <section
      className="policy-proposals hci-card"
      aria-labelledby={compact ? undefined : "policy-proposals-heading"}
      aria-label={compact ? "Suggested rule changes" : undefined}
    >
      {!compact ? (
        <>
          <h3 id="policy-proposals-heading" className="gov-subsection-title">
            Suggested rule changes (optional)
          </h3>
          <p className="gov-help hci-help-tight">
            Incoming suggestions from tools or review. Accept saves a new <strong>inactive</strong> draft — you choose
            when to activate it under Rules.
          </p>
        </>
      ) : null}
      {err ? (
        <div className="hci-inline-err" role="alert">
          {err}
        </div>
      ) : null}
      {actionErr ? (
        <div className="hci-inline-err" role="alert">
          {actionErr}
        </div>
      ) : null}

      {!err && pending.length === 0 ? (
        <p className="muted">No pending proposals.</p>
      ) : null}
      {!err && pending.length > 0 ? (
        <ul className="hci-proposal-list">
          {pending.map((p) => (
            <li key={p.id} className="hci-proposal-item">
              <button
                type="button"
                className="hci-proposal-toggle"
                onClick={() => setOpenId((x) => (x === p.id ? null : p.id))}
                aria-expanded={openId === p.id}
              >
                <span className="mono hci-proposal-id">{p.id.slice(0, 8)}…</span>
                <span className="hci-proposal-meta">
                  {p.source} · {p.created_at.slice(0, 16).replace("T", " ")}
                </span>
              </button>
              {openId === p.id ? (
                <div className="hci-proposal-body">
                  {p.rationale ? <p className="muted">{p.rationale}</p> : null}
                  <pre className="hci-json mono" tabIndex={0}>
                    {JSON.stringify(p.proposed_content, null, 2)}
                  </pre>
                  <div className="hci-proposal-actions">
                    <label className="field-label" htmlFor={`draft-name-${p.id}`}>
                      Draft name (on accept)
                    </label>
                    <input
                      id={`draft-name-${p.id}`}
                      className="hci-input"
                      value={draftName}
                      onChange={(e) => setDraftName(e.target.value)}
                    />
                    <label className="field-label" htmlFor={`note-${p.id}`}>
                      Note (optional)
                    </label>
                    <input
                      id={`note-${p.id}`}
                      className="hci-input"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="Resolution note"
                    />
                    <div className="hci-btn-row">
                      <button
                        type="button"
                        className="btn-sm btn-activate"
                        disabled={busyId === p.id}
                        onClick={() => void act(p.id, "accept")}
                      >
                        {busyId === p.id ? "…" : "Accept → draft"}
                      </button>
                      <button
                        type="button"
                        className="btn-sm btn-deactivate"
                        disabled={busyId === p.id}
                        onClick={() => void act(p.id, "reject")}
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

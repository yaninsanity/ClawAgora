import type { ReceiptRecord } from "../api/client";
import { OpenClawArtifactsList, type OpenClawArtifactRow } from "./OpenClawArtifactsList";

type TrustScore = { value: number; reasons: string[] };
type OptRec = { code: string; message: string; severity: string };
type OptReport = { task_id: string; items: OptRec[] };

export function ReceiptPanel({ receipt }: { receipt: ReceiptRecord }) {
  const body = receipt.body;
  const trust = body.trust_score as TrustScore | undefined;
  const opt = body.optimization as OptReport | undefined;
  const conclusion = body.conclusion as string | undefined;
  const ocArts = body.openclaw_artifacts as OpenClawArtifactRow[] | undefined;

  const pct = trust ? Math.round(trust.value * 100) : null;

  return (
    <div className="receipt-panel">
      {conclusion && (
        <div className="receipt-conclusion">{conclusion}</div>
      )}

      {trust && (
        <div className="receipt-row">
          <span className="receipt-label">Trust</span>
          <div
            className="trust-track"
            role="img"
            aria-label={`Trust score ${pct ?? 0} percent`}
          >
            <div
              className="trust-fill"
              aria-hidden="true"
              style={{
                width: `${pct ?? 0}%`,
                background:
                  pct != null && pct >= 80
                    ? "#2ea44f"
                    : pct != null && pct >= 60
                      ? "#e3a008"
                      : "#cf222e",
              }}
            />
          </div>
          <span className="receipt-pct" aria-hidden="true">
            {pct}%
          </span>
        </div>
      )}

      {trust && trust.reasons.length > 0 && (
        <div className="receipt-reasons">
          {trust.reasons.map((r) => (
            <span key={r} className="pill pill-sm">{r}</span>
          ))}
        </div>
      )}

      {opt && opt.items.length > 0 && (
        <div className="opt-list">
          {opt.items.map((item) => (
            <div key={item.code} className={`opt-item opt-${item.severity}`}>
              <span className="opt-code">{item.code}</span>
              <span className="opt-msg">{item.message}</span>
            </div>
          ))}
        </div>
      )}

      {Array.isArray(ocArts) && ocArts.length > 0 ? (
        <OpenClawArtifactsList items={ocArts} variant="receipt" title="OpenClaw artifacts" />
      ) : null}

      <div className="receipt-hash muted">
        receipt · {receipt.body_hash.slice(0, 16)}
      </div>
    </div>
  );
}

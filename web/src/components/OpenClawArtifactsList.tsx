import { useId } from "react";

export type OpenClawArtifactRow = {
  role?: string;
  content?: string;
  agent_id?: string;
  meta?: unknown;
};

type Variant = "strip" | "receipt";

function coerceMeta(meta: unknown): Record<string, string> | null {
  if (!meta || typeof meta !== "object" || Array.isArray(meta)) return null;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(meta as Record<string, unknown>)) {
    const ks = String(k).trim();
    if (!ks) continue;
    if (typeof v === "string") out[ks] = v;
    else if (v != null && typeof v !== "object") out[ks] = String(v);
  }
  return Object.keys(out).length > 0 ? out : null;
}

function ArtifactMetaChips({ meta }: { meta: Record<string, string> }) {
  const entries = Object.entries(meta).filter(([k]) => k.trim());
  if (entries.length === 0) return null;
  return (
    <div className="oc-artifact-meta-chips" aria-label="Artifact metadata">
      {entries.slice(0, 6).map(([k, v], idx) => (
        <span key={`${k}-${idx}`} className="oc-artifact-meta-chip mono" title={`${k}: ${v}`}>
          {k}: {v.length > 48 ? `${v.slice(0, 48)}…` : v}
        </span>
      ))}
    </div>
  );
}

export function OpenClawArtifactsList({
  items,
  variant,
  title = "Agent lanes",
}: {
  items: OpenClawArtifactRow[];
  variant: Variant;
  /** Strip uses uppercase section title; receipt uses same string with receipt styling. */
  title?: string;
}) {
  const titleId = useId();
  if (items.length === 0) return null;

  const listClass = variant === "strip" ? "openclaw-artifact-list" : "receipt-oc-artifact-list";
  const itemClass = variant === "strip" ? "openclaw-artifact-item" : "receipt-oc-artifact";
  const titleClass = variant === "strip" ? "openclaw-artifacts-title" : "receipt-oc-heading";

  return (
    <div
      className={variant === "strip" ? "openclaw-artifacts-block" : "receipt-openclaw-artifacts"}
      role="region"
      aria-labelledby={titleId}
    >
      <h4 id={titleId} className={titleClass}>
        {title}
      </h4>
      <ol className={listClass}>
        {items.map((a, i) => {
          const role = String(a.role ?? "agent").trim() || "agent";
          const body = String(a.content ?? "").trim();
          const metaNorm = coerceMeta(a.meta);
          return (
            <li key={`${role}-${i}`} className={itemClass}>
              <div className="oc-artifact-head">
                <span className="pill pill-sm oc-artifact-role">{role}</span>
                {a.agent_id ? (
                  <span className="mono muted oc-artifact-agent" title="Agent id">
                    {String(a.agent_id)}
                  </span>
                ) : null}
              </div>
              {metaNorm ? <ArtifactMetaChips meta={metaNorm} /> : null}
              <div
                className="oc-artifact-content mono"
                tabIndex={body.length > 280 ? 0 : undefined}
                aria-label={body.length > 280 ? `${role} output` : undefined}
              >
                {body || "—"}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

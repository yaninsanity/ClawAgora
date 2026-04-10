import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchGovernanceApprovalTemplates,
  fetchOrganizationUnits,
  patchOrganizationUnit,
  type ApprovalPolicyTemplateRow,
  type GovernanceApprovalTemplatesPayload,
  type OrganizationUnitRow,
} from "../api/client";

function MatchPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`hci-pill${ok ? " hci-pill-ok" : " hci-pill-warn"}`} title={label}>
      {label}: {ok ? "match" : "mismatch"}
    </span>
  );
}

export function JudicialQuorumCard() {
  const [orgs, setOrgs] = useState<OrganizationUnitRow[]>([]);
  const [orgsErr, setOrgsErr] = useState<string | null>(null);
  const [base, setBase] = useState<GovernanceApprovalTemplatesPayload | null>(null);
  const [orgSlug, setOrgSlug] = useState("");
  const [scoped, setScoped] = useState<GovernanceApprovalTemplatesPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [scopedLoading, setScopedLoading] = useState(false);
  const [copyOk, setCopyOk] = useState(false);
  const [linkErr, setLinkErr] = useState<string | null>(null);
  const [linkBusy, setLinkBusy] = useState(false);
  const [assignTemplateSlug, setAssignTemplateSlug] = useState("");

  const loadOrgs = useCallback(async () => {
    setOrgsErr(null);
    try {
      setOrgs(await fetchOrganizationUnits());
    } catch (e) {
      setOrgsErr(e instanceof Error ? e.message : String(e));
      setOrgs([]);
    }
  }, []);

  const loadBase = useCallback(async () => {
    setBase(await fetchGovernanceApprovalTemplates());
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await Promise.all([loadOrgs(), loadBase()]);
      } catch (e) {
        if (!cancelled) setOrgsErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadOrgs, loadBase]);

  useEffect(() => {
    if (!orgSlug.trim()) {
      setScoped(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setScopedLoading(true);
      try {
        const p = await fetchGovernanceApprovalTemplates(orgSlug.trim());
        if (!cancelled) setScoped(p);
      } catch {
        if (!cancelled) setScoped(null);
      } finally {
        if (!cancelled) setScopedLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgSlug]);

  const templates: ApprovalPolicyTemplateRow[] = base?.templates ?? [];
  const runtime = base?.runtime;

  const rec = scoped?.org_recommendation as Record<string, unknown> | null | undefined;
  const envExports = useMemo(() => {
    if (!rec || !Array.isArray(rec.env_exports)) return [];
    return rec.env_exports.filter((x): x is string => typeof x === "string");
  }, [rec]);

  const copyEnv = () => {
    const text = envExports.join("\n");
    if (!text) return;
    void navigator.clipboard.writeText(text).then(() => {
      setCopyOk(true);
      window.setTimeout(() => setCopyOk(false), 2000);
    });
  };

  const selectedOrg = orgs.find((o) => o.slug === orgSlug);

  const linkTemplate = async () => {
    if (!selectedOrg || !assignTemplateSlug.trim()) return;
    setLinkErr(null);
    setLinkBusy(true);
    try {
      await patchOrganizationUnit(selectedOrg.id, {
        approval_template_slug: assignTemplateSlug.trim(),
      });
      await loadOrgs();
      const p = await fetchGovernanceApprovalTemplates(orgSlug.trim());
      setScoped(p);
    } catch (e) {
      setLinkErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLinkBusy(false);
    }
  };

  if (loading && !base) {
    return (
      <div className="hci-card hci-card-muted" role="status">
        Loading approval settings…
      </div>
    );
  }

  return (
    <div className="hci-card">
      <h2 id="gov-quorum-heading" className="gov-section-title">
        Human approvals (how many people must sign off)
      </h2>
      <p className="gov-help hci-help-tight">
        Pick a preset (e.g. two-person sign-off). Copy the suggested env lines to your server if you want that
        behavior — the running process must still set those variables.
      </p>

      {orgsErr ? (
        <div className="hci-inline-err" role="alert">
          {orgsErr}
        </div>
      ) : null}

      <div className="hci-field">
        <label className="field-label" htmlFor="judicial-org-select">
          Org scope (optional)
        </label>
        <select
          id="judicial-org-select"
          className="hci-select"
          value={orgSlug}
          onChange={(e) => setOrgSlug(e.target.value)}
          aria-describedby="judicial-org-hint"
        >
          <option value="">— All templates only —</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.slug}>
              {o.name} ({o.slug})
              {o.approval_template_slug ? ` · ${o.approval_template_slug}` : ""}
            </option>
          ))}
        </select>
        <p id="judicial-org-hint" className="muted hci-hint">
          Org units come from GET /api/v1/governance/organization-units/. Empty list is OK for dev.
        </p>
      </div>

      {runtime ? (
        <div className="hci-runtime-strip" role="group" aria-label="Current runtime">
          <div className="gov-stat-row">
            <span className="gov-stat-label">Runtime gate</span>
            <span className="gov-stat-value mono">{runtime.approval_gate_mode}</span>
          </div>
          <div className="gov-stat-row">
            <span className="gov-stat-label">Runtime quorum</span>
            <span className="gov-stat-value">
              {runtime.approval_quorum} (threshold {runtime.majority_threshold})
            </span>
          </div>
        </div>
      ) : null}

      <div className="hci-template-grid" role="table" aria-label="Approval templates">
        <div className="hci-template-row hci-template-head" role="row">
          <span role="columnheader">Template</span>
          <span role="columnheader">Quorum</span>
          <span role="columnheader">Summary</span>
        </div>
        {templates.map((t) => (
          <div key={t.slug} className="hci-template-row" role="row">
            <span className="mono" role="cell">
              {t.slug}
            </span>
            <span role="cell">{t.quorum}</span>
            <span className="muted hci-template-desc" role="cell">
              {t.description ? t.description.slice(0, 120) : "—"}
              {t.description && t.description.length > 120 ? "…" : ""}
            </span>
          </div>
        ))}
      </div>

      {orgSlug ? (
        <div className="hci-org-rec" aria-live="polite">
          <h3 className="gov-subsection-title">Org recommendation</h3>
          {scopedLoading ? (
            <p className="muted">Resolving…</p>
          ) : rec && rec.found === false ? (
            <p className="muted">Unknown org slug.</p>
          ) : rec && typeof rec.note === "string" && rec.recommended_quorum == null ? (
            <p className="muted">{String(rec.note)}</p>
          ) : rec && typeof rec.recommended_quorum === "number" ? (
            <>
              <div className="gov-stat-row">
                <span className="gov-stat-label">Suggested quorum</span>
                <span className="gov-stat-value">
                  {String(rec.recommended_quorum)} (threshold {String(rec.majority_threshold ?? "—")})
                </span>
              </div>
              <div className="hci-match-row">
                {typeof rec.matches_runtime_quorum === "boolean" ? (
                  <MatchPill ok={rec.matches_runtime_quorum as boolean} label="Quorum" />
                ) : null}
                {typeof rec.matches_runtime_gate === "boolean" ? (
                  <MatchPill ok={rec.matches_runtime_gate as boolean} label="Gate" />
                ) : null}
              </div>
              {envExports.length > 0 ? (
                <div className="hci-env-block">
                  <pre className="hci-env-pre mono" tabIndex={0}>
                    {envExports.join("\n")}
                  </pre>
                  <button type="button" className="btn-sm" onClick={() => void copyEnv()}>
                    {copyOk ? "Copied" : "Copy env lines"}
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <p className="muted">No recommendation payload.</p>
          )}

          {selectedOrg ? (
            <fieldset className="hci-fieldset">
              <legend className="field-label">Link template to this org</legend>
              <div className="hci-link-row">
                <select
                  className="hci-select"
                  value={assignTemplateSlug}
                  onChange={(e) => setAssignTemplateSlug(e.target.value)}
                  aria-label="Approval template"
                >
                  <option value="">— Choose template —</option>
                  {templates.map((t) => (
                    <option key={t.slug} value={t.slug}>
                      {t.name} (quorum {t.quorum})
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-sm"
                  disabled={linkBusy || !assignTemplateSlug.trim()}
                  onClick={() => void linkTemplate()}
                >
                  {linkBusy ? "Saving…" : "Save link"}
                </button>
              </div>
              {linkErr ? (
                <p className="hci-inline-err" role="alert">
                  {linkErr}
                </p>
              ) : (
                <p className="muted hci-hint">
                  Requires <span className="mono">X-Governance-Key</span> when the server sets governance write keys.
                </p>
              )}
            </fieldset>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

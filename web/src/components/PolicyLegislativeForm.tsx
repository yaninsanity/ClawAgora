import { useCallback, useId, useMemo, useState } from "react";

export type PolicyExecutorOption = { id: string; label: string };

/** Fallback when GET /governance/executors/ is unavailable (offline / older server). */
export const POLICY_EXECUTOR_FALLBACK: PolicyExecutorOption[] = [
  { id: "executor_transform", label: "Transform" },
  { id: "executor_echo", label: "Echo" },
  { id: "executor_coding", label: "Coding" },
  { id: "executor_research", label: "Research" },
  { id: "executor_support", label: "Support" },
];

export function mergeExecutorOptions(api: PolicyExecutorOption[] | null | undefined): PolicyExecutorOption[] {
  if (!api?.length) return [...POLICY_EXECUTOR_FALLBACK];
  const m = new Map(POLICY_EXECUTOR_FALLBACK.map((o) => [o.id, o]));
  for (const x of api) m.set(x.id, x);
  return Array.from(m.values()).sort((a, b) => a.id.localeCompare(b.id));
}

export type LegislativeFormState = {
  denyRows: string[];
  allowlistEnabled: boolean;
  allowedExecutorIds: string[];
  extraJson: string;
};

export function emptyLegislativeFormState(executorIds: string[]): LegislativeFormState {
  return {
    denyRows: [""],
    allowlistEnabled: false,
    allowedExecutorIds: [...executorIds],
    extraJson: "",
  };
}

/** True when something is set outside the simple name + first block line. */
export function formUsesAdvancedFields(f: LegislativeFormState): boolean {
  if (f.allowlistEnabled) return true;
  if (f.extraJson.trim()) return true;
  if (f.denyRows.length > 1) return true;
  if (f.denyRows.slice(1).some((r) => r.trim().length > 0)) return true;
  return false;
}

export function buildPolicyContentFromForm(
  state: LegislativeFormState,
  validExecutorIds: string[],
): { ok: true; content: Record<string, unknown> } | { ok: false; error: string } {
  const valid = new Set(validExecutorIds);
  let base: Record<string, unknown> = {};
  const trimmed = state.extraJson.trim();
  if (trimmed) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { ok: false, error: "Advanced JSON must be a single object { … }." };
      }
      base = { ...(parsed as Record<string, unknown>) };
    } catch {
      return { ok: false, error: "Advanced JSON is not valid JSON." };
    }
  }

  const deny_patterns = state.denyRows.map((s) => s.trim()).filter((s) => s.length > 0);
  base.deny_patterns = deny_patterns;

  if (state.allowlistEnabled) {
    const allowed = state.allowedExecutorIds.filter((id) => valid.has(id));
    if (allowed.length === 0) {
      return {
        ok: false,
        error: "Allowlist is on but no executors selected — pick at least one or turn off allowlist.",
      };
    }
    base.allowed_executors = allowed;
  } else {
    delete base.allowed_executors;
  }

  return { ok: true, content: base };
}

/** Hydrate the legislative form from a draft's stored content (inverse of buildPolicyContentFromForm). */
export function legislativeFormFromPolicyContent(
  content: Record<string, unknown>,
  executorOptions: PolicyExecutorOption[],
): LegislativeFormState {
  const validIds = executorOptions.map((o) => o.id);
  const deny = content.deny_patterns;
  const denyRows =
    Array.isArray(deny) && deny.every((p): p is string => typeof p === "string")
      ? deny.length > 0
        ? [...deny]
        : [""]
      : [""];
  const allowed = content.allowed_executors;
  const allowlistEnabled =
    Array.isArray(allowed) &&
    allowed.length > 0 &&
    allowed.every((e): e is string => typeof e === "string");
  const allowedExecutorIds = allowlistEnabled
    ? allowed.filter((id) => validIds.includes(id))
    : [...validIds];
  const rest: Record<string, unknown> = { ...content };
  delete rest.deny_patterns;
  delete rest.allowed_executors;
  const extraJson =
    Object.keys(rest).length > 0 ? JSON.stringify(rest, null, 2) : "";
  return { denyRows, allowlistEnabled, allowedExecutorIds, extraJson };
}

type Props = {
  policyName: string;
  onPolicyNameChange: (v: string) => void;
  form: LegislativeFormState;
  onFormChange: (next: LegislativeFormState) => void;
  /** From GET /api/v1/governance/executors/ merged with fallback — legislative allowlist matches runtime. */
  executorOptions: PolicyExecutorOption[];
  executorSource: "server" | "fallback";
  error: string | null;
  onSubmit: () => void;
  submitDisabled: boolean;
  /** When true, Advanced settings starts expanded (e.g. loading a draft that uses advanced fields). */
  initialAdvancedOpen?: boolean;
  formMode?: "create" | "edit";
  onCancelEdit?: () => void;
};

export function PolicyLegislativeForm({
  policyName,
  onPolicyNameChange,
  form,
  onFormChange,
  executorOptions,
  executorSource,
  error,
  onSubmit,
  submitDisabled,
  initialAdvancedOpen = false,
  formMode = "create",
  onCancelEdit,
}: Props) {
  const baseId = useId();
  /* Start simple: advanced (regex rows, tools, expert JSON) stays closed until the user opens it. */
  const [rulesAdvancedOpen, setRulesAdvancedOpen] = useState(initialAdvancedOpen);

  const validIds = useMemo(() => executorOptions.map((o) => o.id), [executorOptions]);

  const toggleExecutor = useCallback(
    (id: string, checked: boolean) => {
      const set = new Set(form.allowedExecutorIds);
      if (checked) set.add(id);
      else set.delete(id);
      onFormChange({
        ...form,
        allowedExecutorIds: validIds.filter((x) => set.has(x)),
      });
    },
    [form, onFormChange, validIds],
  );

  const denyHintId = `${baseId}-deny-hint`;
  const allowlistId = `${baseId}-allowlist`;

  const selectedCount = useMemo(
    () => form.allowedExecutorIds.filter((id) => validIds.includes(id)).length,
    [form.allowedExecutorIds, validIds],
  );

  const firstBlockLine = form.denyRows[0] ?? "";

  const setFirstDenyRow = useCallback(
    (v: string) => {
      const next = [...form.denyRows];
      if (next.length === 0) next.push(v);
      else next[0] = v;
      onFormChange({ ...form, denyRows: next });
    },
    [form, onFormChange],
  );

  const advancedSummary = useMemo(() => {
    const extraRows = Math.max(0, form.denyRows.length - 1);
    const parts: string[] = [];
    if (extraRows > 0) parts.push(`${extraRows} extra block line${extraRows === 1 ? "" : "s"}`);
    if (form.allowlistEnabled) parts.push("tool limit on");
    if (form.extraJson.trim()) parts.push("expert JSON");
    return parts.join(" · ");
  }, [form.denyRows.length, form.allowlistEnabled, form.extraJson]);

  return (
    <div className="policy-form policy-form-structured">
      <div className="policy-form-flow-hint" role="region" aria-label="How rules apply">
        <span className="policy-form-flow-title">How this works</span>
        <ol className="policy-form-flow-steps">
          <li>
            {formMode === "edit" ? (
              <>
                <strong>Save changes</strong> to update this draft in the list <strong>above</strong>. If it is already
                on, new tasks pick up the update right away.
              </>
            ) : (
              <>
                <strong>Save a draft</strong> with the button at the bottom — it appears in the list <strong>above</strong>{" "}
                this form.
              </>
            )}
          </li>
          <li>
            <strong>Turn rules on or off</strong> — use <strong>Turn on</strong> / <strong>Turn off</strong> on each row.
            Only one set can be on at a time; turning another on switches automatically.
          </li>
        </ol>
      </div>

      <div className="policy-form-section">
        <label className="policy-field-label" htmlFor={`${baseId}-name`}>
          Name this rule set
        </label>
        <input
          id={`${baseId}-name`}
          className="input-sm"
          placeholder="e.g. block-password-in-text"
          value={policyName}
          onChange={(e) => onPolicyNameChange(e.target.value)}
          autoComplete="off"
        />
        <p className="policy-field-hint muted policy-hint-tight">
          Shown in the list above. You can keep several drafts; only one can be <strong>on</strong> at a time.
        </p>
      </div>

      {!rulesAdvancedOpen ? (
        <div className="policy-field-block policy-form-section">
          <label className="policy-field-label" htmlFor={`${baseId}-block-simple`}>
            Block certain text (optional)
          </label>
          <p id={denyHintId} className="policy-field-hint muted">
            If the task text matches, the run can stop here. One line for now — add more under Advanced. Regex ok
            (e.g. <span className="mono">{String.raw`\bpassword\b`}</span>).
          </p>
          <input
            id={`${baseId}-block-simple`}
            className="input-sm policy-deny-input"
            placeholder={String.raw`e.g. \bpassword\b — or leave empty`}
            value={firstBlockLine}
            onChange={(e) => setFirstDenyRow(e.target.value)}
            aria-describedby={denyHintId}
          />
          {formUsesAdvancedFields(form) ? (
            <p className="policy-simple-advanced-note muted" role="status">
              Advanced options are in use — open <strong>Advanced settings</strong> to edit them.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="policy-field-block policy-form-section">
          <span className="policy-field-label" id={`${baseId}-deny-label`}>
            Block if input matches (regex, one line each)
          </span>
          <p id={denyHintId} className="policy-field-hint muted">
            If input matches a line, the task can be stopped at validation. Leave all empty for no text blocks.
          </p>
          <div
            className="policy-deny-rows"
            role="group"
            aria-labelledby={`${baseId}-deny-label`}
            aria-describedby={denyHintId}
          >
            {form.denyRows.map((row, i) => (
              <div key={i} className="policy-deny-row">
                <input
                  className="input-sm policy-deny-input"
                  placeholder={i === 0 ? String.raw`e.g. \bpassword\b` : "regex pattern"}
                  value={row}
                  onChange={(e) => {
                    const next = [...form.denyRows];
                    next[i] = e.target.value;
                    onFormChange({ ...form, denyRows: next });
                  }}
                  aria-label={`Deny pattern ${i + 1}`}
                />
                <button
                  type="button"
                  className="btn-sm policy-row-remove"
                  disabled={form.denyRows.length <= 1}
                  onClick={() => {
                    if (form.denyRows.length <= 1) return;
                    const next = form.denyRows.filter((_, j) => j !== i);
                    onFormChange({ ...form, denyRows: next.length ? next : [""] });
                  }}
                  aria-label="Remove this pattern row"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="btn-sm policy-add-row"
            onClick={() => onFormChange({ ...form, denyRows: [...form.denyRows, ""] })}
          >
            + Add line
          </button>
        </div>
      )}

      <div className="policy-advanced policy-advanced-unified">
        <button
          type="button"
          className="policy-advanced-toggle"
          aria-expanded={rulesAdvancedOpen}
          onClick={() => setRulesAdvancedOpen((o) => !o)}
        >
          {rulesAdvancedOpen ? "▼" : "▶"}{" "}
          {rulesAdvancedOpen ? "Hide advanced settings" : "Advanced settings"}
          {!rulesAdvancedOpen && advancedSummary ? (
            <span className="policy-advanced-badge muted"> — {advancedSummary}</span>
          ) : null}
        </button>

        {rulesAdvancedOpen ? (
          <div className="policy-advanced-body policy-advanced-body-wide">
            <div className="policy-field-block">
              <span className="policy-field-label" id={`${baseId}-exec-label`}>
                Limit which tools can run (optional)
              </span>
              <label className="policy-toggle-row" htmlFor={allowlistId}>
                <input
                  id={allowlistId}
                  type="checkbox"
                  checked={form.allowlistEnabled}
                  onChange={(e) => {
                    const on = e.target.checked;
                    onFormChange({
                      ...form,
                      allowlistEnabled: on,
                      allowedExecutorIds:
                        on && form.allowedExecutorIds.length === 0 ? [...validIds] : form.allowedExecutorIds,
                    });
                  }}
                />
                <span>Only allow the tools I select below</span>
              </label>
              <p className="policy-field-hint muted">
                {executorSource === "server" ? (
                  <>List matches this server&apos;s live tool registry.</>
                ) : (
                  <>Using a built-in list — connect to the server to sync.</>
                )}{" "}
                Off = server defaults. On = only checked tools.
              </p>
              {form.allowlistEnabled ? (
                <div className="policy-executor-grid">
                  <div className="policy-field-label" style={{ marginTop: 8 }}>
                    Allowed tools
                  </div>
                  <div className="policy-executor-chips" aria-live="polite">
                    {executorOptions.map((opt) => (
                      <label key={opt.id} className="policy-exec-chip">
                        <input
                          type="checkbox"
                          checked={form.allowedExecutorIds.includes(opt.id)}
                          onChange={(e) => toggleExecutor(opt.id, e.target.checked)}
                        />
                        <span>{opt.label}</span>
                        <span className="policy-exec-id mono">{opt.id}</span>
                      </label>
                    ))}
                  </div>
                  <div className="policy-exec-toolbar">
                    <span className="muted policy-exec-count">
                      {selectedCount} of {validIds.length} selected
                    </span>
                    <button
                      type="button"
                      className="policy-exec-bulk"
                      onClick={() => onFormChange({ ...form, allowedExecutorIds: [...validIds] })}
                    >
                      All
                    </button>
                    <button
                      type="button"
                      className="policy-exec-bulk"
                      onClick={() => onFormChange({ ...form, allowedExecutorIds: [] })}
                    >
                      Clear
                    </button>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="policy-expert-json-block">
              <span className="policy-field-label">Expert only: extra JSON</span>
              <p className="muted policy-field-hint">
                Most teams can <strong>ignore this</strong>. If you use it: merged first, then the form overwrites{" "}
                <code className="code-inline">deny_patterns</code> and <code className="code-inline">allowed_executors</code>.
              </p>
              <textarea
                className="textarea-sm"
                placeholder="{}"
                value={form.extraJson}
                onChange={(e) => onFormChange({ ...form, extraJson: e.target.value })}
                spellCheck={false}
              />
            </div>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="policy-form-err" role="alert">
          {error}
        </div>
      ) : null}

      <div className="policy-form-submit-row">
        <button
          type="button"
          className="btn-sm policy-submit-btn"
          onClick={onSubmit}
          disabled={submitDisabled}
          aria-describedby={`${baseId}-submit-hint`}
        >
          {formMode === "edit" ? "Save changes" : "Save draft to list"}
        </button>
        {formMode === "edit" && onCancelEdit ? (
          <button type="button" className="btn-sm policy-cancel-edit-btn" onClick={onCancelEdit}>
            Cancel editing
          </button>
        ) : null}
      </div>
      <p id={`${baseId}-submit-hint`} className="policy-action-hint muted">
        {formMode === "edit" ? (
          <>
            Updates apply to the selected draft. Use <strong>Turn on</strong> in the list if you want this set to drive
            new tasks.
          </>
        ) : (
          <>
            Then go to the list <strong>above</strong> and press the green <strong>Turn on</strong> button on the draft you
            want — that step applies rules to new tasks.
          </>
        )}
      </p>
    </div>
  );
}

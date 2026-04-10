type Props = {
  onReplayTour: () => void;
};

/**
 * Minimal visible path + one closed-by-default disclosure for long product copy.
 * Keeps the main workspace scannable and improves keyboard/AT focus patterns on summary.
 */
export function OptionalProductHelp({ onReplayTour }: Props) {
  return (
    <section
      id="optional-help"
      className="optional-help"
      aria-labelledby="optional-help-quick-h"
      aria-describedby="optional-help-context"
      tabIndex={-1}
    >
      <h2 id="optional-help-quick-h" className="optional-help-quick-title">
        Quick reference
      </h2>
      <p className="optional-help-context muted" id="optional-help-context">
        How goals become agent runs, receipts, and managed work — below the workspace above.
      </p>
      <p className="optional-help-one-liner">
        <strong>Left:</strong> state a <strong>goal</strong>, send it with <strong>Send request</strong>.{" "}
        <strong>Right:</strong> <strong>Review</strong> to queue, reopen, and approve; <strong>Rules</strong> /{" "}
        <strong>Safety</strong> to constrain how agents may act.
      </p>
      <ol className="optional-help-steps">
        <li>
          One <strong>goal</strong> per run — <strong>Progress</strong> shows stages, <strong>Outcome</strong> shows output,
          <strong>Receipt</strong> records success for audit.
        </li>
        <li>
          <strong>Review</strong> is your control tower: reopen, retry, or approve without losing history.
        </li>
        <li>
          Add <strong>Rules</strong> / <strong>Safety</strong> when you need predictable, policy-aligned agent behavior.
        </li>
      </ol>
      <div className="optional-help-actions">
        <button type="button" className="btn-sm optional-help-tour-btn" onClick={onReplayTour}>
          Replay guided tour
        </button>
      </div>

      <details className="help-deep-dive">
        <summary className="product-help-summary help-deep-dive-summary disclosure-summary-a11y">
          <span className="help-deep-dive-summary-text">Definitions, governance map, and comparison table</span>
          <span className="help-deep-dive-summary-hint muted"> — optional reading</span>
        </summary>
        <div className="help-deep-dive-body">
          <h3 className="help-deep-dive-h3">Terms</h3>
          <dl className="product-help-dl help-deep-dive-dl">
            <dt>Goal</dt>
            <dd>What you state in the main box — the outcome the agent should work toward.</dd>
            <dt>Send request</dt>
            <dd>Main action; runs one handled request end to end.</dd>
            <dt>Progress</dt>
            <dd>Stages already completed, in order.</dd>
            <dt>Review</dt>
            <dd>Queue and history on the right.</dd>
            <dt>Rules</dt>
            <dd>Allow/block patterns (policy drafts).</dd>
            <dt>Safety</dt>
            <dd>Org strictness and health snapshots.</dd>
            <dt>Receipt</dt>
            <dd>Short record when a run succeeds.</dd>
          </dl>

          <h3 className="help-deep-dive-h3">Where each kind of work lives</h3>
          <div className="powers-coverage-strip" role="group" aria-label="Coverage map">
            <div className="powers-coverage-item">
              <span className="powers-coverage-label">Intake &amp; queue</span>
              <span className="powers-coverage-where">Send request · Review</span>
            </div>
            <div className="powers-coverage-item">
              <span className="powers-coverage-label">Policy</span>
              <span className="powers-coverage-where">Rules</span>
            </div>
            <div className="powers-coverage-item">
              <span className="powers-coverage-label">Trace</span>
              <span className="powers-coverage-where">Progress · Outcome · Receipt</span>
            </div>
            <div className="powers-coverage-item">
              <span className="powers-coverage-label">Sign-off &amp; posture</span>
              <span className="powers-coverage-where">Review · Safety</span>
            </div>
          </div>

          <div className="powers-grid help-deep-dive-powers-grid" role="list">
            <article className="powers-card powers-card--legislative" role="listitem">
              <h4 className="powers-card-title powers-card-title--compact">
                <span className="powers-branch" aria-hidden="true">
                  I
                </span>
                Legislative — <strong>Rules</strong>
              </h4>
              <p className="powers-card-body">
                Allow/block patterns; activate drafts. Change when permissions are wrong.
              </p>
            </article>
            <article className="powers-card powers-card--executive" role="listitem">
              <h4 className="powers-card-title powers-card-title--compact">
                <span className="powers-branch" aria-hidden="true">
                  II
                </span>
                Executive — <strong>Send · Progress · Outcome</strong>
              </h4>
              <p className="powers-card-body">
                Left column runs the request. Change when execution or planning fails.
              </p>
            </article>
            <article className="powers-card powers-card--judicial" role="listitem">
              <h4 className="powers-card-title powers-card-title--compact">
                <span className="powers-branch" aria-hidden="true">
                  III
                </span>
                Judicial — <strong>Review · Safety</strong>
              </h4>
              <p className="powers-card-body">
                Approvals queue and org-wide strictness. Change when sign-off or posture is off.
              </p>
            </article>
          </div>

          <h3 className="help-deep-dive-h3">Compared with fixed “department” routing</h3>
          <ul className="separation-powers-compare-list help-deep-dive-list">
            <li>
              <strong>Same jobs</strong> — inbox, policy, execution, oversight — with a <strong>per-run trace</strong>.
            </li>
            <li>
              <strong>Clear levers</strong> — adjust Rules, rerun the request, or tune Review/Safety separately.
            </li>
          </ul>

          <h3 className="help-deep-dive-h3">Job → tab</h3>
          <div className="separation-powers-table-wrap">
            <table className="separation-powers-table">
              <caption className="separation-powers-caption">
                Map common jobs to tabs and panels
              </caption>
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Typical silo habit</th>
                  <th scope="col">Here</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Inbox &amp; status</td>
                  <td>Counter queue</td>
                  <td>
                    <strong>Review</strong>
                  </td>
                </tr>
                <tr>
                  <td>Policy</td>
                  <td>Handbook</td>
                  <td>
                    <strong>Rules</strong>
                  </td>
                </tr>
                <tr>
                  <td>What happened when</td>
                  <td>Reconstructed later</td>
                  <td>
                    <strong>Progress</strong>, <strong>Outcome</strong>, <strong>Receipt</strong>
                  </td>
                </tr>
                <tr>
                  <td>Sign-off</td>
                  <td>Approval desk</td>
                  <td>
                    <strong>Review</strong> · approval on open run
                  </td>
                </tr>
                <tr>
                  <td>Org strictness</td>
                  <td>Central directive</td>
                  <td>
                    <strong>Safety</strong>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </details>

      <p className="optional-help-back muted">
        <a href="#main-content" className="header-help-jump-link">
          Back to request form
        </a>
        <span aria-hidden="true"> · </span>
        <a href="#workspace-sidebar" className="header-help-jump-link">
          Workspace sidebar
        </a>
      </p>
    </section>
  );
}

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { dismissOnboarding } from "../onboardingStorage";

type Step = 1 | 2 | 3;

type Props = {
  onOpenReviewTab: () => void;
  onOpenRulesTab: () => void;
  onDismissed: () => void;
};

export function FirstRunOnboarding({ onOpenReviewTab, onOpenRulesTab, onDismissed }: Props) {
  const titleId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [step, setStep] = useState<Step>(1);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const finish = useCallback(() => {
    dismissOnboarding();
    onDismissed();
  }, [onDismissed]);

  const goNext = useCallback(() => {
    if (step === 1) setStep(2);
    else if (step === 2) setStep(3);
    else finish();
  }, [step, finish]);

  const goBack = useCallback(() => {
    if (step === 2) setStep(1);
    else if (step === 3) setStep(2);
  }, [step]);

  return (
    <section className="onboarding-card" role="region" aria-labelledby={titleId}>
      <div className="onboarding-card-header">
        <h2 id={titleId} ref={headingRef} className="onboarding-card-title" tabIndex={-1}>
          Welcome — quick tour{" "}
          <span className="onboarding-step-pill" aria-live="polite" aria-atomic="true">
            Step {step} of 3
          </span>
        </h2>
        <button type="button" className="btn-sm onboarding-skip" onClick={finish} aria-label="Skip introduction">
          Skip
        </button>
      </div>

      {step === 1 ? (
        <div className="onboarding-body">
          <p className="onboarding-value muted">
            You <strong>define the goal</strong>; the agent runs through <strong>visible stages</strong>; you{" "}
            <strong>manage</strong> the queue and optional <strong>rules / sign-off</strong> — not a disposable chat.
          </p>
          <p className="onboarding-lead">
            <strong>1 — Try it once.</strong> Use the big box on the <strong>left</strong> to state an outcome, then press{" "}
            <kbd className="kbd-inline">Send request</kbd>.
          </p>
          <p className="onboarding-detail muted">
            You&apos;ll see <strong>Progress</strong>, then <strong>Outcome</strong> and often a <strong>receipt</strong> when
            it succeeds. No setup or code required for this step.
          </p>
          <p className="onboarding-tour-note" role="note">
            This card only explains the screen — <strong>Next</strong> does not send anything. To run real work, always
            use <strong>Send request</strong> on the left.
          </p>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="onboarding-body">
          <p className="onboarding-lead">
            <strong>2 — Find it again.</strong> Open <strong>Review</strong> on the right — that&apos;s your history and
            queue. Click a row to open it here; approve or fix if the system asks.
          </p>
          <p className="onboarding-detail muted">
            Use <strong>Needs approval</strong> or <strong>Needs fix</strong> to see only items that need you.
          </p>
          <button type="button" className="btn-sm onboarding-jump" onClick={() => onOpenReviewTab()}>
            Go to Review
          </button>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="onboarding-body">
          <p className="onboarding-lead">
            <strong>3 — Later: extra control.</strong> <strong>Rules</strong> allow or block patterns;{" "}
            <strong>Safety</strong> is for org-wide strictness. Both are optional.
          </p>
          <p className="onboarding-detail muted">
            Skip until someone on your team asks for it. The product splits <strong>law</strong> (Rules),{" "}
            <strong>execution</strong> (left column + Progress), and <strong>judgment</strong> (Review + Safety) so you fix
            the right layer. Heavier options sit under <strong>Advanced — background run or OpenClaw</strong> — ignore until
            your admin points you there.
          </p>
          <button type="button" className="btn-sm onboarding-jump" onClick={() => onOpenRulesTab()}>
            Go to Rules
          </button>
        </div>
      ) : null}

      <div className="onboarding-footer">
        {step > 1 ? (
          <button type="button" className="btn-sm onboarding-back" onClick={goBack}>
            Back
          </button>
        ) : (
          <span />
        )}
        <div className="onboarding-nav-right">
          {step < 3 ? (
            <button type="button" className="btn-sm onboarding-next" onClick={goNext}>
              {step === 1 ? "Next tip" : "Next"}
            </button>
          ) : (
            <button type="button" className="btn-sm onboarding-next" onClick={finish}>
              Done
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

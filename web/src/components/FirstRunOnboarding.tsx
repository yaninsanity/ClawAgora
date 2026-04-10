import { useCallback, useId, useState } from "react";
import { dismissOnboarding } from "../onboardingStorage";

type Step = 1 | 2 | 3;

type Props = {
  onOpenReviewTab: () => void;
  onOpenRulesTab: () => void;
  onDismissed: () => void;
};

export function FirstRunOnboarding({ onOpenReviewTab, onOpenRulesTab, onDismissed }: Props) {
  const titleId = useId();
  const [step, setStep] = useState<Step>(1);

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
        <h2 id={titleId} className="onboarding-card-title">
          First steps{" "}
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
          <p className="onboarding-lead">
            <strong>1 — Try a run.</strong> Use the big box on the <strong>left</strong>, then press{" "}
            <kbd className="kbd-inline">Run task</kbd>.
          </p>
          <p className="onboarding-detail muted">
            You&apos;ll see status and output here when it finishes. Nothing else is required for a first try.
          </p>
          <p className="onboarding-tour-note" role="note">
            This card is only a quick tour — <strong>Next</strong> does not run anything. To actually run work, always
            use <strong>Run task</strong> on the left.
          </p>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="onboarding-body">
          <p className="onboarding-lead">
            <strong>2 — Check the queue.</strong> Open <strong>Review</strong> on the right. Click a row to open it
            here — approve or request changes if your server asks.
          </p>
          <p className="onboarding-detail muted">
            Use <strong>Needs approval</strong> or <strong>Needs fix</strong> to shorten the list.
          </p>
          <button type="button" className="btn-sm onboarding-jump" onClick={() => onOpenReviewTab()}>
            Go to Review
          </button>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="onboarding-body">
          <p className="onboarding-lead">
            <strong>3 — Later: extra control.</strong> <strong>Rules</strong> blocks or allows patterns;{" "}
            <strong>Safety</strong> sets how strict checks are. Both are optional.
          </p>
          <p className="onboarding-detail muted">
            Skip this step until you care — defaults work fine while you explore. For OpenClaw bridges, optional
            session and memory IDs live under <strong>Need background run or OpenClaw?</strong> when you run a task.
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

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchGovernanceDashboard,
  fetchGovernanceProfiles,
  fetchGovernanceSummary,
  fetchOpenClawStatus,
  type GovernanceDashboard,
  type GovernanceProfiles,
  type GovernanceSummary,
  type OpenClawStatus,
} from "../api/client";

const SUMMARY_RETRY_DELAY_MS = 650;

/**
 * Loads profiles, dashboard, governance summary (with stale-safe retry), and OpenClaw status.
 * Uses a monotonic generation counter so overlapping refreshes do not corrupt UI state.
 */
export function useGovernanceRefresh() {
  const [govProfiles, setGovProfiles] = useState<GovernanceProfiles | null>(null);
  const [govDashboard, setGovDashboard] = useState<GovernanceDashboard | null>(null);
  const [govSummary, setGovSummary] = useState<GovernanceSummary | null>(null);
  const [govSummaryFailed, setGovSummaryFailed] = useState(false);
  const [govSummaryRetrying, setGovSummaryRetrying] = useState(false);
  const [govRefreshing, setGovRefreshing] = useState(false);
  const [openClaw, setOpenClaw] = useState<OpenClawStatus | null>(null);

  const govRefreshSeq = useRef(0);
  const summaryRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshGovernance = useCallback(async () => {
    setGovRefreshing(true);
    try {
      if (summaryRetryTimerRef.current != null) {
        clearTimeout(summaryRetryTimerRef.current);
        summaryRetryTimerRef.current = null;
      }
      const seq = ++govRefreshSeq.current;
      setGovSummaryRetrying(false);

      const settled = await Promise.allSettled([
        fetchGovernanceProfiles(),
        fetchGovernanceDashboard(),
        fetchGovernanceSummary(),
      ]);

      if (seq !== govRefreshSeq.current) return;

      if (settled[0].status === "fulfilled") setGovProfiles(settled[0].value);
      if (settled[1].status === "fulfilled") setGovDashboard(settled[1].value);
      if (settled[2].status === "fulfilled") {
        setGovSummary(settled[2].value);
        setGovSummaryFailed(false);
        setGovSummaryRetrying(false);
      } else {
        setGovSummaryFailed(true);
        summaryRetryTimerRef.current = setTimeout(() => {
          summaryRetryTimerRef.current = null;
          void (async () => {
            if (seq !== govRefreshSeq.current) return;
            setGovSummaryRetrying(true);
            try {
              const s = await fetchGovernanceSummary();
              if (seq !== govRefreshSeq.current) return;
              setGovSummary(s);
              setGovSummaryFailed(false);
            } catch {
              if (seq !== govRefreshSeq.current) return;
              setGovSummaryFailed(true);
            } finally {
              if (seq === govRefreshSeq.current) setGovSummaryRetrying(false);
            }
          })();
        }, SUMMARY_RETRY_DELAY_MS);
      }

      try {
        const oc = await fetchOpenClawStatus();
        if (seq !== govRefreshSeq.current) return;
        setOpenClaw(oc);
      } catch {
        if (seq !== govRefreshSeq.current) return;
        setOpenClaw(null);
      }
    } finally {
      setGovRefreshing(false);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (summaryRetryTimerRef.current != null) {
        clearTimeout(summaryRetryTimerRef.current);
        summaryRetryTimerRef.current = null;
      }
      govRefreshSeq.current += 1;
    };
  }, []);

  return {
    govProfiles,
    govDashboard,
    govSummary,
    govSummaryFailed,
    govSummaryRetrying,
    govRefreshing,
    openClaw,
    refreshGovernance,
  };
}

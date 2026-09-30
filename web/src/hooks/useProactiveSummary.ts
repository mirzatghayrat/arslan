import { useCallback, useEffect, useState } from "react";
import { PROACTIVE_CHANGED, proactiveApi, type ProactiveSummary } from "../api/proactive";

const POLL_MS = 30_000;
const NONE: ProactiveSummary = { open: 0, unread: 0, high: 0 };

/** The inbox badge. Polls every 30 s while the window is visible, and immediately when anything
 * in the app changes the inbox. A failed poll keeps the last number: a restarting service should
 * not make the badge flicker to zero. */
export function useProactiveSummary(): ProactiveSummary {
  const [summary, setSummary] = useState<ProactiveSummary>(NONE);
  const load = useCallback(() => proactiveApi.summary().then(setSummary).catch(() => { /* keep the last number */ }), []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    const onChange = () => void load();
    window.addEventListener(PROACTIVE_CHANGED, onChange);
    document.addEventListener("visibilitychange", onChange);
    return () => { clearInterval(timer); window.removeEventListener(PROACTIVE_CHANGED, onChange); document.removeEventListener("visibilitychange", onChange); };
  }, [load]);
  return summary;
}

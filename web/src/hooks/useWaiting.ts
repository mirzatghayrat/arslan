import { useCallback, useEffect, useState } from "react";
import { PROACTIVE_CHANGED, proactiveApi, type Waiting } from "../api/proactive";

const POLL_MS = 30_000;
const NONE: Waiting = { count: 0, conversations: [], projects: [], scheduled: [] };

/** INB5: what is waiting on you, as the server counts it (progress.waiting_on_user: conversations, projects and scheduled tasks,
 *  never rows), for the badge on Progress. Polls every 30 s while the window is visible, and at once when anything in the app changes
 *  a reminder or a card. A failed poll keeps the last number: a restarting service should not make the badge flicker to zero. */
export function useWaiting(): Waiting {
  const [waiting, setWaiting] = useState<Waiting>(NONE);
  const load = useCallback(() => proactiveApi.summary().then((summary) => { if (summary?.waiting) setWaiting(summary.waiting); })
    .catch(() => { /* keep the last number */ }), []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    const onChange = () => void load();
    window.addEventListener(PROACTIVE_CHANGED, onChange);
    document.addEventListener("visibilitychange", onChange);
    return () => { clearInterval(timer); window.removeEventListener(PROACTIVE_CHANGED, onChange); document.removeEventListener("visibilitychange", onChange); };
  }, [load]);
  return waiting;
}

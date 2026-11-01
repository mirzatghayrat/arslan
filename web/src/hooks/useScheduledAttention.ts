import { useCallback, useEffect, useRef, useState } from "react";
import { api, request } from "../api/client";
import type { ScheduledTaskDto } from "../api/client.types";
import { PROACTIVE_CHANGED, proactiveApi, type ProactiveItem } from "../api/proactive";
import type { Refusal } from "../components/proactive/NotDoneList";

const POLL_MS = 30_000;
/** The server's longest window (1 to 168 hours): a weekly task's away entries stay until its next run. */
export const AWAY_HOURS = 168;

/** The conversation a task's runs write into, as the scheduler names it (scheduler.py). */
export const scheduledConversation = (task: Pick<ScheduledTaskDto, "id" | "conversation_id">) =>
  task.conversation_id || `scheduled-${task.id}`;

export interface TaskAttention {
  /** Its last run failed, or it was paused after failing three times in a row (a pause by hand is no problem). */
  failing: boolean;
  /** Its open "scheduled_problem" reminders (source `sched:<id>`). */
  problems: ProactiveItem[];
  /** How many things one of its runs could not do while nobody was there to ask. Two tasks writing into one conversation
   *  share these: the entries do not say which task's run asked. */
  away: number;
}

export interface ScheduledAttention {
  tasks: Record<number, TaskAttention>;
  /** A watch's open page or folder changes (source `watch:<id>`), by watch id; only watches that still exist (a removed watch's
   *  changes have no row to show them on, so they must not light the sidebar). */
  changes: Record<number, ProactiveItem[]>;
  /** Anything above: the sidebar's dot. */
  any: boolean;
  reload: () => Promise<void>;
}

const bySource = (items: ProactiveItem[], prefix: string, kinds: string[]) => {
  const out: Record<number, ProactiveItem[]> = {};
  for (const item of items) {
    const id = item.source_key?.startsWith(prefix) ? Number(item.source_key.slice(prefix.length)) : NaN;
    if (kinds.includes(item.kind) && Number.isInteger(id)) (out[id] ??= []).push(item);
  }
  return out;
};

/**
 * INB3: what on the Scheduled page needs a look (the INB card's dots). Polls every 30 s while the window is visible, at once when
 * it shows again or something changes a reminder. A failed poll keeps the last state, so a restarting service does not make the
 * dots flicker; a load that a newer one overtook is dropped. INB5 replaces this with the server's one count of what waits for you.
 */
export function useScheduledAttention(): ScheduledAttention {
  const [state, setState] = useState<Omit<ScheduledAttention, "reload">>({ tasks: {}, changes: {}, any: false });
  const latest = useRef(0);
  const load = useCallback(async () => {
    const mine = ++latest.current;
    try {
      const [tasks, { items }, { watches }] = await Promise.all([api.listScheduledTasks(), proactiveApi.items("open"), proactiveApi.watches()]);
      // One request per task: the server keeps each conversation's entries apart only when asked for one (#568). One that fails
      // fails the load, which keeps the last state rather than dropping that task's dot.
      const away = await Promise.all(tasks.map((task) => {
        const query = new URLSearchParams({ hours: String(AWAY_HOURS), conversation_id: scheduledConversation(task) });
        return request<Refusal[]>(`/approvals/refused?${query}`).then((rows) => rows.filter((row) => row.unattended).length);
      }));
      if (mine !== latest.current) return;
      const problems = bySource(items, "sched:", ["scheduled_problem"]);
      const watched = new Set(watches.map((watch) => watch.id));
      const changes = Object.fromEntries(Object.entries(bySource(items, "watch:", ["web_change", "folder_change"]))
        .filter(([id]) => watched.has(Number(id))));
      const byTask: Record<number, TaskAttention> = {};
      tasks.forEach((task, i) => {
        byTask[task.id] = { failing: task.paused_reason != null || task.last_outcome === "error", problems: problems[task.id] ?? [], away: away[i] };
      });
      const any = Object.values(byTask).some((a) => a.failing || a.problems.length > 0 || a.away > 0) || Object.keys(changes).length > 0;
      setState({ tasks: byTask, changes, any });
    } catch { /* keep the last state */ }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    const onChange = () => void load();
    const onVisible = () => { if (document.visibilityState === "visible") void load(); };
    window.addEventListener(PROACTIVE_CHANGED, onChange);
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(timer); window.removeEventListener(PROACTIVE_CHANGED, onChange); document.removeEventListener("visibilitychange", onVisible); };
  }, [load]);
  return { ...state, reload: load };
}

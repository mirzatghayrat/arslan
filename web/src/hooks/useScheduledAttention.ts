import { useCallback, useEffect, useRef, useState } from "react";
import { api, request } from "../api/client";
import type { ScheduledTaskDto } from "../api/client.types";
import { PROACTIVE_CHANGED, proactiveApi, type ProactiveItem, type ProactiveKind } from "../api/proactive";
import type { Refusal } from "../components/proactive/NotDoneList";
import { hasRow, isOpen } from "../lib/proactive";

const POLL_MS = 30_000;
/** The reminders the page shows under a task or a watch. Q7: asked for one kind at a time, so a busier kind (a conversation's job
 *  reminders) never pushes these out of the server's newest hundred. */
const PAGE_KINDS: ProactiveKind[] = ["scheduled_problem", "web_change", "folder_change"];
/** #605 re-check N2: an answer, an open or a reminder acted on each announce a change; a burst of them reads once, this long after the
 *  last, instead of one request per task each time. */
const SETTLE_MS = 1_000;
/** The server's longest window (1 to 168 hours): a weekly task's away entries stay until its next run. */
export const AWAY_HOURS = 168;

/** The conversation a task's runs write into, as the scheduler names it (scheduler.py). */
export const scheduledConversation = (task: Pick<ScheduledTaskDto, "id" | "conversation_id">) =>
  task.conversation_id || `scheduled-${task.id}`;

export interface TaskAttention {
  /** Its last run failed, or it was paused after failing three times in a row (a pause by hand is no problem). */
  failing: boolean;
  /** Its "scheduled_problem" reminders that keep a row (Q7, lib/proactive.hasRow): open ones first, then the ones set aside or handled. */
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
  /** Each watch's changes that keep a row (Q7): its open ones, and the ones set aside or handled, with their state and no dot. */
  changeRows: Record<number, ProactiveItem[]>;
  /** The sidebar's dot: a task the server counts as waiting on you (INB5b-3: its one count, `waiting.scheduled`), or a watch's change,
   *  which the server does not count (#605 review F7). */
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
 * it shows again, and a moment after something changes a reminder or a card. A failed poll keeps the last state, so a restarting
 * service does not make the dots flicker; a load that a newer one overtook is dropped. INB5b-3: whether a task waits on you is the
 * server's one count (`waitingTasks`, progress.waiting_on_user), which knows a card in the task's own conversation and what was seen;
 * this keeps what the page shows under a task, and the watches' changes.
 */
export function useScheduledAttention(waitingTasks: number[] = []): ScheduledAttention {
  const [state, setState] = useState<Omit<ScheduledAttention, "reload" | "any">>({ tasks: {}, changes: {}, changeRows: {} });
  const latest = useRef(0);
  const load = useCallback(async () => {
    const mine = ++latest.current;
    try {
      const [tasks, { items }, { watches }, ...kinds] = await Promise.all([api.listScheduledTasks(), proactiveApi.items("open"),
        proactiveApi.watches(), ...PAGE_KINDS.map((kind) => proactiveApi.items("all", { kind }))]);
      // One request per task: the server keeps each conversation's entries apart only when asked for one (#568). One that fails
      // fails the load, which keeps the last state rather than dropping that task's dot.
      const away = await Promise.all(tasks.map((task) => {
        const query = new URLSearchParams({ hours: String(AWAY_HOURS), conversation_id: scheduledConversation(task) });
        return request<Refusal[]>(`/approvals/refused?${query}`).then((rows) => rows.filter((row) => row.unattended).length);
      }));
      if (mine !== latest.current) return;
      // Every open one (the dots), and each kind's rows that are kept (Q7), once each: open ones first, then the newest.
      const now = Date.now();
      const byId = new Map<number, ProactiveItem>();
      for (const item of [...items, ...kinds.flatMap((kind) => kind.items)]) if (hasRow(item, now)) byId.set(item.id, item);
      const rows = [...byId.values()].sort((a, b) => Number(isOpen(b)) - Number(isOpen(a)) || b.id - a.id);
      const problems = bySource(rows, "sched:", ["scheduled_problem"]);
      const watched = new Set(watches.map((watch) => watch.id));
      const ofWatches = (list: ProactiveItem[]) => Object.fromEntries(Object.entries(bySource(list, "watch:", ["web_change", "folder_change"]))
        .filter(([id]) => watched.has(Number(id))));
      const changes = ofWatches(items.filter(isOpen));
      const changeRows = ofWatches(rows);
      const byTask: Record<number, TaskAttention> = {};
      tasks.forEach((task, i) => {
        byTask[task.id] = { failing: task.paused_reason != null || task.last_outcome === "error", problems: problems[task.id] ?? [], away: away[i] };
      });
      setState({ tasks: byTask, changes, changeRows });
    } catch { /* keep the last state */ }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    let soon: ReturnType<typeof setTimeout> | undefined;
    const onChange = () => { clearTimeout(soon); soon = setTimeout(() => void load(), SETTLE_MS); };
    const onVisible = () => { if (document.visibilityState === "visible") void load(); };
    window.addEventListener(PROACTIVE_CHANGED, onChange);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer); clearTimeout(soon);
      window.removeEventListener(PROACTIVE_CHANGED, onChange); document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);
  return { ...state, any: waitingTasks.length > 0 || Object.keys(state.changes).length > 0, reload: load };
}

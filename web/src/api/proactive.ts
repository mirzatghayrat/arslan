import { request } from "./client";

// 0.1.47 proactivity. Text arrives as KEYS + params (see locales/proactive.ts); only `goal`,
// which a background job will be asked to do, is prose.
export type ProactiveKind = "job_followup" | "scheduled_problem" | "web_change" | "folder_change" | "brief";
export type ProactiveStatus = "new" | "seen" | "accepted" | "snoozed" | "dismissed" | "expired";
export interface ProactiveEvidence { key: string; params: Record<string, unknown>; quote?: string }
export interface ProactiveItem {
  id: number; kind: ProactiveKind; title_key: string; params: Record<string, unknown>;
  evidence: ProactiveEvidence[]; goal: string; priority: "high" | "normal" | "low"; status: ProactiveStatus;
  diagnosis: { cause: string; next_step: string; model: string; usd: number } | null;
  conversation_id: string | null; job_id: string | null; created_at: string; snooze_until: string | null;
  /** INB3: where it came from: `watch:<id>` for a page or folder, `sched:<id>` for a scheduled task. */
  source_key?: string | null;
}
export interface ProactiveSummary {
  open: number; unread: number; high: number;
  /** 0.1.55 §12: cards waiting for approval (any conversation or job). Memory is not counted since
   *  v0.1.64 (INB1/INB2): what did not take effect is listed in Memory, it does not wait for an OK. */
  approvals?: number;
  /** INB5: what is waiting on you, counted once (progress.waiting_on_user); the badge on Progress reads `count`. */
  waiting?: Waiting;
}
/** INB5: units, never rows: a conversation, a project, or a scheduled task. */
export interface Waiting { count: number; conversations: string[]; projects: string[]; scheduled: number[] }
export interface ProactiveConfig {
  enabled: boolean; notify: boolean; notify_daily_cap: number; quiet_start: string; quiet_end: string;
  job_followups: boolean; scheduled_problems: boolean; watches: boolean; brief_enabled: boolean; brief_time: string;
  diagnosis_daily_usd: number;
}
export interface ProactiveWatch {
  id: number; kind: "web" | "folder"; target: string; label: string; enabled: boolean; interval_s: number;
  notify: boolean; last_error: string | null; last_checked_at: string | null; last_changed_at: string | null;
}
export type ProactiveScope = "open" | "snoozed" | "done" | "all";
export type MuteChoice = "source" | "kind";

/** Anything that changes what is waiting on you (a reminder acted on, a card answered) announces it here, so the badge on
 * Progress does not wait for its next poll. */
export const PROACTIVE_CHANGED = "arslan:proactive-changed";
export const announceProactiveChange = () => { try { window.dispatchEvent(new Event(PROACTIVE_CHANGED)); } catch { /* no window */ } };

const send = (method: string, body?: unknown) => ({ method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
const changed = async <T>(call: Promise<T>): Promise<T> => { const out = await call; announceProactiveChange(); return out; };

export const proactiveApi = {
  summary: () => request<ProactiveSummary>("/proactive/summary"),
  /** INB5b: `conversationId` and `kind` narrow the list, so a conversation reads only its own stopped-job reminders. */
  items: (scope: ProactiveScope = "open", only: { conversationId?: string; kind?: ProactiveKind } = {}) => {
    // A filter given empty is sent, not dropped: the server refuses it, rather than listing every conversation's items (#602 review).
    const query = new URLSearchParams({ scope, ...(only.conversationId !== undefined ? { conversation_id: only.conversationId } : {}),
      ...(only.kind !== undefined ? { kind: only.kind } : {}) });
    return request<{ items: ProactiveItem[] }>(`/proactive/items?${query}`);
  },
  seen: (ids: number[]) => changed(request<{ ok: boolean }>("/proactive/items/seen", send("POST", { ids }))),
  accept: (id: number, conversationId?: string) => changed(request<{ job_id: string; conversation_id: string }>(
    `/proactive/items/${id}/accept`, send("POST", conversationId ? { conversation_id: conversationId } : {}))),
  snooze: (id: number, days: 1 | 3 | 7) => changed(request<{ ok: boolean }>(`/proactive/items/${id}/snooze`, send("POST", { days }))),
  dismiss: (id: number, mute?: MuteChoice) => changed(request<{ ok: boolean }>(
    `/proactive/items/${id}/dismiss`, send("POST", { mute: mute ?? null }))),
  config: () => request<ProactiveConfig>("/proactive/config"),
  saveConfig: (patch: Partial<ProactiveConfig>) => changed(request<ProactiveConfig>("/proactive/config", send("PUT", patch))),
  watches: () => request<{ watches: ProactiveWatch[] }>("/proactive/watches"),
  addWatch: (body: { kind: "web" | "folder"; target: string; label?: string; interval_s: number; notify: boolean }) =>
    changed(request<ProactiveWatch>("/proactive/watches", send("POST", body))),
  updateWatch: (id: number, patch: Partial<Pick<ProactiveWatch, "enabled" | "notify" | "interval_s" | "label">>) =>
    changed(request<ProactiveWatch>(`/proactive/watches/${id}`, send("PATCH", patch))),
  deleteWatch: (id: number) => changed(request<{ ok: boolean }>(`/proactive/watches/${id}`, send("DELETE"))),
  mutes: () => request<{ mutes: string[] }>("/proactive/mutes"),
  unmute: (key: string) => changed(request<{ ok: boolean }>(`/proactive/mutes?key=${encodeURIComponent(key)}`, send("DELETE"))),
  scan: () => changed(request<{ created: number; rejected: Record<string, number> }>("/proactive/scan", send("POST"))),
};

/** What each conversation is and how it stands (GET /conversations: kind, state, origin, job) —
 *  the sidebar's glyphs and the Remote trace. The phone's own conversation is "pocket", shown as
 *  Remote everywhere. */
import type { ServerConversation } from "./sessionPersistence";

export type ConversationKind = "remote" | "chat" | "task" | "scheduled";
/** INB4: `done_unseen` is a reply or a job done the window has not shown yet. */
export type ConversationState = "idle" | "working" | "waiting" | "done" | "done_unseen" | "unfinished" | "failed";
export interface ConversationJob { id: string; step: string; done: number; total: number }
export interface ConversationMeta {
  kind: ConversationKind;
  state: ConversationState;
  origin: "phone" | "mac";
  files: number;
  job?: ConversationJob | null;
  /** 0.1.58 §4: the project it belongs to (null = none). */
  projectId?: string | null;
  /** SB1: the server's last activity (ISO), for the sidebar's order and sections. */
  lastAt?: string | null;
  /** SB1-2: pinned to the top of the sidebar (the server's record). */
  pinned?: boolean;
  /** INB5b-3: what a waiting row waits on. Unset when it does not wait, or on an older server, which reads as a card. */
  waitingOn?: WaitingOn;
}

/** INB5b-3: what a waiting conversation waits on (the server's `waiting_on`): a card to approve (a decision), a card that went
 *  unanswered while you were away (nothing is left to approve, only the list of what was not done; ⓪Plan's review of PR 614, N2), or
 *  a stopped job's reminder (an offer). */
export type WaitingOn = "card" | "away" | "reminder";
/** Most urgent first, as the server's waiting_reasons ranks them. */
const WAITING_ON: readonly WaitingOn[] = ["card", "away", "reminder"];

/** A project row's reason: the most urgent of its waiting conversations', where one with no reason (an older server) counts as a card.
 *  So the project shows the bell only when every one of them waits on a reminder (⓪Plan's review of PR 614, N1). */
export const mostUrgent = (reasons: (WaitingOn | undefined)[]): WaitingOn =>
  WAITING_ON.find((reason) => reasons.some((r) => (r ?? "card") === reason)) ?? "card";

/** The glyph's label for a waiting row, by what it waits on (sidebar.glyph.*). */
export const waitingLabel = (waitingOn?: WaitingOn) =>
  waitingOn === "reminder" ? "waiting_reminder" : waitingOn === "away" ? "waiting_away" : "waiting";

// DELETE-BY: v0.1.64 if the iPhone's Quick Ask (Q1c) ships with it, else v0.1.65 (Q1 card, #4; the user, 2026-10-29): the pocket ("Remote") stays only for phones that don't say `quick`.
export const REMOTE_ID = "pocket";
const KINDS: ConversationKind[] = ["remote", "chat", "task", "scheduled"];
const STATES: ConversationState[] = ["idle", "working", "waiting", "done", "done_unseen", "unfinished", "failed"];

/** The server writes times as naive UTC ("2026-10-30T07:00:00", no offset: server/api/conversations.py),
 *  and a string with no offset is read as LOCAL time by Date.parse. Mark such a time UTC; one that already
 *  carries "Z" or an offset is kept as it is. (⓪Plan's review of PR 543: in UTC+8, 07:00 today read as
 *  yesterday; west of UTC, times looked like the future.) */
export function utcIso(time: string): string {
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(time) ? time : `${time}Z`;
}

export function metaFrom(rows: ServerConversation[]): Record<string, ConversationMeta> {
  const out: Record<string, ConversationMeta> = {};
  for (const row of rows) {
    // DELETE-BY: with REMOTE_ID (Q1 card, #4): the pocket read as "remote" when the server says no kind.
    const kind = KINDS.includes(row.kind as ConversationKind) ? (row.kind as ConversationKind)
      : row.conversation_id === REMOTE_ID ? "remote" : "chat";
    out[row.conversation_id] = {
      kind,
      state: STATES.includes(row.state as ConversationState) ? (row.state as ConversationState) : "idle",
      origin: row.origin === "phone" ? "phone" : "mac",
      files: typeof row.files === "number" ? row.files : 0,
      job: row.job ?? null,
      projectId: typeof row.project_id === "string" && row.project_id ? row.project_id : null,
      lastAt: typeof row.last_at === "string" && row.last_at ? utcIso(row.last_at) : null,
      pinned: row.pinned === true,
      ...(row.state === "waiting" && WAITING_ON.includes(row.waiting_on as WaitingOn) ? { waitingOn: row.waiting_on as WaitingOn } : {}),
    };
  }
  return out;
}

/** Remote first, then the rest in the order given. */
// DELETE-BY: v0.1.64 if the iPhone's Quick Ask (Q1c) ships with it, else v0.1.65 (Q1 card, #4; the user, 2026-10-29): the pocket ("Remote") stays only for phones that don't say `quick`.
export function remoteFirst<T extends { id: string }>(threads: T[], meta: Record<string, ConversationMeta>): T[] {
  const isRemote = (t: T) => t.id === REMOTE_ID || meta[t.id]?.kind === "remote";
  return [...threads.filter(isRemote), ...threads.filter(t => !isRemote(t))];
}

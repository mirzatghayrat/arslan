/** What each conversation is and how it stands (GET /conversations: kind, state, origin, job) —
 *  the sidebar's glyphs and the Remote trace. The phone's own conversation is "pocket", shown as
 *  Remote everywhere. */
import type { ServerConversation } from "./sessionPersistence";

export type ConversationKind = "remote" | "chat" | "task" | "scheduled";
export type ConversationState = "idle" | "working" | "waiting" | "done" | "unfinished" | "failed";
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
}

// DELETE-BY: v0.1.64 if the iPhone's Quick Ask (Q1c) ships with it, else v0.1.65 (Q1 card, #4; the user, 2026-10-29): the pocket ("Remote") stays only for phones that don't say `quick`.
export const REMOTE_ID = "pocket";
const KINDS: ConversationKind[] = ["remote", "chat", "task", "scheduled"];
const STATES: ConversationState[] = ["idle", "working", "waiting", "done", "unfinished", "failed"];

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

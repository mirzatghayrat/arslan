/** What each conversation is and how it stands (GET /conversations: kind, state, origin, job) —
 *  the sidebar's glyphs and the Remote trace. The phone's own conversation is "pocket", shown as
 *  Remote everywhere. */
import type { ServerConversation } from "./sessionPersistence";

export type ConversationKind = "remote" | "chat" | "task" | "scheduled";
export type ConversationState = "idle" | "working" | "waiting" | "done" | "failed";
export interface ConversationJob { id: string; step: string; done: number; total: number }
export interface ConversationMeta {
  kind: ConversationKind;
  state: ConversationState;
  origin: "phone" | "mac";
  files: number;
  job?: ConversationJob | null;
}

export const REMOTE_ID = "pocket";
const KINDS: ConversationKind[] = ["remote", "chat", "task", "scheduled"];
const STATES: ConversationState[] = ["idle", "working", "waiting", "done", "failed"];

export function metaFrom(rows: ServerConversation[]): Record<string, ConversationMeta> {
  const out: Record<string, ConversationMeta> = {};
  for (const row of rows) {
    const kind = KINDS.includes(row.kind as ConversationKind) ? (row.kind as ConversationKind)
      : row.conversation_id === REMOTE_ID ? "remote" : "chat";
    out[row.conversation_id] = {
      kind,
      state: STATES.includes(row.state as ConversationState) ? (row.state as ConversationState) : "idle",
      origin: row.origin === "phone" ? "phone" : "mac",
      files: typeof row.files === "number" ? row.files : 0,
      job: row.job ?? null,
    };
  }
  return out;
}

/** Remote first, then the rest in the order given. */
export function remoteFirst<T extends { id: string }>(threads: T[], meta: Record<string, ConversationMeta>): T[] {
  const isRemote = (t: T) => t.id === REMOTE_ID || meta[t.id]?.kind === "remote";
  return [...threads.filter(isRemote), ...threads.filter(t => !isRemote(t))];
}

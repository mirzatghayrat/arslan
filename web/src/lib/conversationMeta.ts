/** What each conversation is and how it stands (GET /conversations: kind, state, origin, job) —
 *  the sidebar's glyphs and the Remote trace. The old pocket ("Remote") is retired (Q1 card, #4): it is an
 *  ordinary conversation here. */
import type { ServerConversation } from "./sessionPersistence";

export type ConversationKind = "chat" | "task" | "scheduled";
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
}

const KINDS: ConversationKind[] = ["chat", "task", "scheduled"];
const STATES: ConversationState[] = ["idle", "working", "waiting", "done", "unfinished", "failed"];

export function metaFrom(rows: ServerConversation[]): Record<string, ConversationMeta> {
  const out: Record<string, ConversationMeta> = {};
  for (const row of rows) {
    const kind = KINDS.includes(row.kind as ConversationKind) ? (row.kind as ConversationKind) : "chat";
    out[row.conversation_id] = {
      kind,
      state: STATES.includes(row.state as ConversationState) ? (row.state as ConversationState) : "idle",
      origin: row.origin === "phone" ? "phone" : "mac",
      files: typeof row.files === "number" ? row.files : 0,
      job: row.job ?? null,
      projectId: typeof row.project_id === "string" && row.project_id ? row.project_id : null,
    };
  }
  return out;
}

/** SUB5d (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md): sub-sessions as a tree under the conversation that
 *  started them (the commander), built from GET /conversations' `parent_id`. */
import type { ConversationMeta, ConversationState } from "./conversationMeta";

/** What a sub-session's status icon shows: running (a spinning ring), waiting on you (a breathing dot), done (a check). */
export type SubStatus = "running" | "waiting" | "done";

export function subStatus(state?: ConversationState): SubStatus {
  return state === "working" ? "running" : state === "waiting" ? "waiting" : "done";
}

export interface Forest {
  /** Each conversation's sub-sessions, in the order they were given. */
  children: Record<string, string[]>;
  /** Each nested sub-session's parent. One whose parent is not listed (deleted, or kept as a top-level chat) is not in it. */
  parentOf: Record<string, string>;
}

/** The trees among `ids`. A sub-session is nested only when its parent is listed too and the chain has no loop. */
export function buildForest(ids: string[], meta: Record<string, ConversationMeta | undefined>): Forest {
  const listed = new Set(ids);
  const children: Record<string, string[]> = {};
  const parentOf: Record<string, string> = {};
  const loops = (id: string) => {
    const seen = new Set([id]);
    for (let at = meta[id]?.parentId; at; at = meta[at]?.parentId) {
      if (seen.has(at)) return true;
      seen.add(at);
    }
    return false;
  };
  for (const id of ids) {
    const parent = meta[id]?.parentId;
    if (!parent || !listed.has(parent) || loops(id)) continue;
    parentOf[id] = parent;
    (children[parent] ??= []).push(id);
  }
  return { children, parentOf };
}

/** Every sub-session under `id`, at every level. */
export function descendants(id: string, forest: Forest): string[] {
  const out: string[] = [];
  const walk = (at: string) => { for (const child of forest.children[at] ?? []) { out.push(child); walk(child); } };
  walk(id);
  return out;
}

/** The conversations above `id`, nearest first. */
export function ancestors(id: string, forest: Forest): string[] {
  const out: string[] = [];
  for (let at = forest.parentOf[id]; at && !out.includes(at); at = forest.parentOf[at]) out.push(at);
  return out;
}

/** Whether something under `id` is still at work: running, or waiting on you. */
export function busyBelow(id: string, forest: Forest, meta: Record<string, ConversationMeta | undefined>): boolean {
  return descendants(id, forest).some((child) => subStatus(meta[child]?.state) !== "done");
}

/** A flat list as trees: each top-level row in the given order, followed by its sub-sessions, nested (the project's tab). */
export function treeOrder<T extends { conversation_id: string; parent_id?: string | null }>(rows: T[]): { row: T; depth: number }[] {
  const meta = Object.fromEntries(rows.map((row) => [row.conversation_id, { parentId: row.parent_id ?? undefined } as ConversationMeta]));
  const forest = buildForest(rows.map((row) => row.conversation_id), meta);
  const byId = new Map(rows.map((row) => [row.conversation_id, row]));
  const out: { row: T; depth: number }[] = [];
  const walk = (row: T, depth: number) => {
    out.push({ row, depth });
    for (const child of forest.children[row.conversation_id] ?? []) walk(byId.get(child)!, depth + 1);
  };
  rows.filter((row) => !(row.conversation_id in forest.parentOf)).forEach((row) => walk(row, 0));
  return out;
}

/** The approved rule: a tree with a running or waiting sub-session starts open; a finished one starts closed. */
export const startsOpen = busyBelow;

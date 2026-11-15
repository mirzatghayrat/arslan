import { request } from "./client";

/** SIDE-1's listing item (server/services/side_chats.py `_item`). */
export interface SideChat {
  conversation_id: string;
  parent_id: string;
  branch_message_id: number | null;
  /** Card, rule 3: it started as having read outside content (unknown counts as yes, server side). */
  outside_at_start: boolean;
  created_at: string;
  message_count: number;
  last_at: string | null;
}

const base = (parentId: string) => `/conversations/${encodeURIComponent(parentId)}/side-chats`;

/** SIDE-2 (v0.1.64): the side chats of a conversation (SIDE-1's routes). */
export const sideChatsApi = {
  /** Oldest first. */
  list: (parentId: string) => request<SideChat[]>(base(parentId)),
  /** No branch: at the parent's newest message (the panel's "+"). */
  create: (parentId: string, branchMessageId?: number | null) => request<SideChat>(base(parentId), {
    method: "POST", body: JSON.stringify(branchMessageId != null ? { branch_message_id: branchMessageId } : {}),
  }),
  /** A side chat is deleted only when the delete names it as one. */
  remove: (sideId: string) => request<unknown>(`/conversations/${encodeURIComponent(sideId)}?side_chat=true`, { method: "DELETE" }),
};

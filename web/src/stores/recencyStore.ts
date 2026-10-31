import { create } from "zustand";

/**
 * SB1: when this window last saw activity in a conversation — a message sent, a reply finished, a
 * result posted, a conversation started. The sidebar takes the later of this and the server's
 * `last_at` (polled every 8 s), so a conversation moves to the top at once, not at the next poll.
 * In memory only: after a reload the server's `last_at` already carries it.
 */
interface RecencyState {
  touched: Record<string, number>;
  touch: (conversationId: string, at?: number) => void;
}

export const useRecency = create<RecencyState>((set) => ({
  touched: {},
  touch: (conversationId, at = Date.now()) =>
    set((s) => ({ touched: { ...s.touched, [conversationId]: Math.max(at, s.touched[conversationId] ?? 0) } })),
}));

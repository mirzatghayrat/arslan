/** Which thread a clicked desktop notification may open, if any (0.1.41).
 *  Only an existing, non-archived conversation: the id arrives from outside the
 *  page, so it selects from what the user already has, never creates one. */
export function conversationToOpen(id: string, threads: { id: string; archived?: boolean }[]): string | null {
  const thread = threads.find(t => t.id === id);
  return thread && !thread.archived ? thread.id : null;
}

/** What the desktop shell sends when a proactive notice is clicked: not a conversation, the
 *  Inbox. It cannot collide with a real id (those are `thread-<uuid>`). */
export const INBOX_TARGET = "@inbox";

/** Where a clicked desktop notification leads: the Inbox, a conversation the user has, or
 *  nowhere (an id the page does not know is data, not a route). */
export function notificationTarget(id: string, threads: { id: string; archived?: boolean }[]):
  { kind: "inbox" } | { kind: "conversation"; id: string } | null {
  if (id === INBOX_TARGET) return { kind: "inbox" };
  const target = conversationToOpen(id, threads);
  return target ? { kind: "conversation", id: target } : null;
}

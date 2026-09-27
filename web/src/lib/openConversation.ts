/** Which thread a clicked desktop notification may open, if any (0.1.41).
 *  Only an existing, non-archived conversation: the id arrives from outside the
 *  page, so it selects from what the user already has, never creates one. */
export function conversationToOpen(id: string, threads: { id: string; archived?: boolean }[]): string | null {
  const thread = threads.find(t => t.id === id);
  return thread && !thread.archived ? thread.id : null;
}

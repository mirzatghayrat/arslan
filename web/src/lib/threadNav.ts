/** Decide what a click on a conversation row must do.
 *
 * THE BUG THIS FIXES (v0.1.7): the handler unconditionally reset the store and
 * then set the active id, relying on the WebSocket to reconnect under the new
 * conversation_id and push a `history` frame. Clicking the thread you are
 * ALREADY on breaks that assumption — the id does not change, so the socket URL
 * does not change, so useWebSocket never reconnects and no history ever
 * arrives. The chat went blank until you clicked a DIFFERENT thread and came
 * back, which is why it took "two switches" to reappear. It also fired a
 * spurious `session_ended` for a conversation that was not ending.
 *
 * Extracted as a pure function so the decision is testable without mounting the
 * whole App: the reset is the destructive half, and "did we reset when we
 * should not have" is exactly what needs pinning. */
export type ThreadNavAction = {
  /** End the outgoing conversation (background distillation runs on this). */
  endPrevious: boolean;
  /** Wipe the live store — only safe when a history frame is guaranteed to follow. */
  resetStore: boolean;
};

export function threadNavAction(
  currentId: string | null | undefined,
  nextId: string,
): ThreadNavAction {
  // Same thread: the view is merely being brought back into focus. Nothing is
  // ending and nothing will re-send history, so touching either is destructive.
  if (currentId && currentId === nextId) {
    return { endPrevious: false, resetStore: false };
  }
  return { endPrevious: Boolean(currentId), resetStore: true };
}

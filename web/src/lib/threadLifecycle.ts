/**
 * Shared thread-selection decision for the conversation lifecycle handlers
 * (archive / delete). After a thread is removed or archived, the active
 * conversation must never point at a hidden thread: pick the first remaining
 * NON-archived thread, or signal that a fresh session must be minted.
 *
 * Both handlers route through this so archive and delete stay consistent — in
 * particular, archiving the ONLY non-archived thread mints a fresh session just
 * like deleting the last thread does.
 */
export interface ThreadRef {
  id: string;
  archived?: boolean;
}

/**
 * Find the first non-archived thread other than `mutatedId`. Returns `null`
 * when none remain — the caller must then mint a fresh "New Session".
 */
export function firstLiveThread<T extends ThreadRef>(
  threads: readonly T[],
  mutatedId: string,
): T | null {
  return threads.find((th) => th.id !== mutatedId && !th.archived) ?? null;
}

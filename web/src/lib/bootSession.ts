/**
 * bootSession.ts — what the app opens on.
 *
 * The rule the user asked for: launching Arslan lands you in a NEW session, not
 * back in whatever you were reading last week. The obvious risk is that empty
 * sessions then pile up, one per launch, forever.
 *
 * WHY THERE IS NO "IS THIS SESSION EMPTY" FLAG
 *
 * The first design carried a marker on a thread — set when minted, cleared when
 * the user sends — so a launch could REUSE the previous empty session instead of
 * minting another. An adversarial review killed it, and the reasons are worth
 * keeping because they are not obvious:
 *
 *  - The clear had to happen on send, and the send path lives in the zustand
 *    store (arslanStore.ts noteUserSend), which has no access to `threads` or
 *    persistThreads. Clearing there clears nothing durable. The marker would
 *    stay set through a 40-message conversation, and the NEXT launch would
 *    "reuse" that conversation as your new session and append to it. Nothing
 *    in-session looks wrong; it only appears after a process restart.
 *  - Archiving a marked thread kept the marker (handleArchiveThread spreads the
 *    thread), so a later launch could open on a thread the sidebar filters out
 *    of the visible list — an active conversation with no row.
 *  - persistThreads writes the whole array blind, with no read-modify-write, so
 *    a second window silently clobbers a field living inside that blob.
 *
 * So instead of tracking emptiness, this asks the only party that actually
 * knows. A conversation row exists server-side only once it has at least one
 * message (server/api/conversations.py), so "the server has never heard of this
 * thread" IS "this thread has no messages" — no flag, nothing to keep in sync,
 * and nothing that can go stale.
 *
 * Always mint, then prune what the server does not know. At most one empty
 * session exists at a time, and it is the one you are looking at.
 */

import { makeFreshThread, type PersistedThread, type RestoredThreads } from "./sessionPersistence";

export interface BootPlan {
  /** Front-ordered: the session being opened is always index 0. */
  threads: PersistedThread[];
  activeThreadId: string;
  /** True when this plan created a thread that did not exist before. */
  minted: boolean;
}

/**
 * Decide which session the app opens on.
 *
 * `freshLaunch` distinguishes a real app launch from a same-tab reload
 * (consumeFreshSessionFlag). A reload must land exactly where it left off —
 * yanking someone out of what they are reading because the page refreshed would
 * be a bug, not a feature.
 */
export function planBoot(
  restored: RestoredThreads,
  opts: { freshLaunch: boolean; now: number },
): BootPlan {
  if (!opts.freshLaunch) {
    return { threads: restored.threads, activeThreadId: restored.activeThreadId, minted: false };
  }

  // restoreThreads already had to invent a thread — first run, a wiped store, or
  // the packaged app's origin partition changing under it. That thread IS a new
  // empty session; minting a second one beside it would put two of them in the
  // sidebar on a clean install.
  if (restored.mintedFresh) {
    return { threads: restored.threads, activeThreadId: restored.activeThreadId, minted: false };
  }

  const fresh = makeFreshThread(opts.now);
  return {
    // Front, matching where mergeServerConversations puts threads the server has
    // not seen, so nothing jumps under the cursor when the merge lands.
    threads: [fresh, ...restored.threads],
    activeThreadId: fresh.id,
    minted: true,
  };
}

/**
 * Drop sessions that were never used, so launching does not accrete them.
 *
 * Runs only after `GET /conversations` returns rows, which makes it fail-open in
 * the way that matters: a backend still booting, an offline app, or a 401
 * prunes NOTHING rather than deciding everything is empty.
 *
 * Three exemptions, and each one is a bug if removed:
 *   - the ACTIVE thread, or launching would delete the session you are sitting
 *     in before you type your first word;
 *   - ARCHIVED threads, which the user kept deliberately;
 *   - anything the server knows, which by definition has messages.
 */
export function pruneEmptyThreads<T extends { id: string; archived?: boolean }>(
  merged: readonly T[],
  opts: { serverIds: ReadonlySet<string>; activeThreadId: string },
): T[] {
  return merged.filter(
    (t) => opts.serverIds.has(t.id) || t.id === opts.activeThreadId || t.archived === true,
  );
}

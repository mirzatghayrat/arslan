/**
 * sessionPersistence.ts — persist & restore the orchestrator thread list +
 * active thread id across app loads, plus a fresh-session flag used to make the
 * spawn roster session-ephemeral.
 *
 * Design notes:
 *  - Conversations PERSIST and RESUME (full history replays from the backend
 *    `history` frame on connect — we never persist `Message[]` here, the
 *    `history` field is always restored as `[]`).
 *  - We persist only `{id, title, memberSpawnIds, history: []}` per thread + the
 *    active id, in `localStorage`.
 *  - The active-spawn roster is SESSION-EPHEMERAL: a brand-new tab/app launch is
 *    detected via a `sessionStorage` nonce that is ABSENT on first launch and
 *    PRESENT across same-tab reloads.
 *
 * Kept pure / dependency-light so it is easy to unit-test.
 */

/** Minimal shape of a persisted thread (history is never persisted). */
export interface PersistedThread {
  id: string;
  title: string;
  history: [];
  memberSpawnIds?: string[];
  archived?: boolean;
}

export interface RestoredThreads {
  threads: PersistedThread[];
  activeThreadId: string;
}

export const THREADS_KEY = "arslan.threads";
export const ACTIVE_THREAD_KEY = "arslan.activeThreadId";
export const SESSION_KEY = "arslan.session";

/** A thread shape with possibly-populated history (as held in app state). */
interface ThreadLike {
  id: string;
  title: string;
  history?: unknown[];
  memberSpawnIds?: string[];
  archived?: boolean;
}

/**
 * Persist the threads list + active id to localStorage. The `history` field is
 * intentionally dropped (replaced with `[]`) — message history comes from the
 * backend `history` frame, not localStorage.
 */
export function persistThreads(
  threads: ThreadLike[],
  activeThreadId: string,
): void {
  try {
    const slim: PersistedThread[] = threads.map((t) => ({
      id: t.id,
      title: t.title,
      history: [],
      ...(t.memberSpawnIds ? { memberSpawnIds: t.memberSpawnIds } : {}),
      ...(t.archived ? { archived: true } : {}),
    }));
    localStorage.setItem(THREADS_KEY, JSON.stringify(slim));
    localStorage.setItem(ACTIVE_THREAD_KEY, activeThreadId);
  } catch {
    /* storage unavailable (private mode / quota) — best-effort, ignore */
  }
}

/** Build a single fresh thread (used on first run / post-wipe). */
function makeFreshThread(): PersistedThread {
  return {
    id: `thread-${Date.now()}`,
    title: "New Session",
    history: [],
    memberSpawnIds: [],
  };
}

/**
 * Restore the persisted threads + active id. If nothing valid is stored, returns
 * a single fresh `thread-${Date.now()}` titled "New Session" as the active one.
 * Never reintroduces a literal "thread-default".
 */
export function restoreThreads(): RestoredThreads {
  let threads: PersistedThread[] = [];
  let activeThreadId = "";
  try {
    const rawThreads = localStorage.getItem(THREADS_KEY);
    if (rawThreads) {
      const parsed = JSON.parse(rawThreads);
      if (Array.isArray(parsed)) {
        threads = parsed
          .filter(
            (t): t is { id: string; title: string; memberSpawnIds?: string[]; archived?: boolean } =>
              !!t && typeof t.id === "string" && typeof t.title === "string",
          )
          .map((t) => ({
            id: t.id,
            title: t.title,
            history: [] as [],
            ...(Array.isArray(t.memberSpawnIds)
              ? { memberSpawnIds: t.memberSpawnIds }
              : {}),
            ...(t.archived === true ? { archived: true } : {}),
          }));
      }
    }
    activeThreadId = localStorage.getItem(ACTIVE_THREAD_KEY) ?? "";
  } catch {
    threads = [];
    activeThreadId = "";
  }

  // First run / post-wipe / corrupt store → start with one fresh thread.
  if (threads.length === 0) {
    const fresh = makeFreshThread();
    return { threads: [fresh], activeThreadId: fresh.id };
  }

  // If the stored active id no longer points at a thread, fall back to the first.
  if (!threads.some((t) => t.id === activeThreadId)) {
    activeThreadId = threads[0].id;
  }

  return { threads, activeThreadId };
}

/**
 * Returns true exactly once per fresh app session: true on a brand-new tab/app
 * launch (no sessionStorage nonce), false on subsequent same-tab reloads. Has
 * the side effect of writing the nonce, so it must be called once on init.
 */
export function consumeFreshSessionFlag(): boolean {
  try {
    const fresh = !sessionStorage.getItem(SESSION_KEY);
    sessionStorage.setItem(SESSION_KEY, "1");
    return fresh;
  } catch {
    // sessionStorage unavailable — treat as NOT fresh so we never reset a
    // roster we can't track (conservative: avoids clobbering on every render).
    return false;
  }
}

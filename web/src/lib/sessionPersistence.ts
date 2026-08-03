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
  /**
   * True when nothing valid was stored and the thread below was invented here.
   *
   * bootSession.planBoot needs to tell "the store was empty so I made one" apart
   * from "the user has threads", because on a fresh launch it mints a new
   * session — and minting beside an already-invented one would show two empty
   * sessions on a clean install. The packaged app hits this constantly: an
   * ephemeral sidecar port changes the origin, so localStorage reads as absent
   * on launches that are not first runs at all.
   */
  mintedFresh: boolean;
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

/**
 * Build a single fresh thread — first run, post-wipe, or a new session at boot.
 *
 * `now` is injected rather than read from the clock so the id is a function of
 * its input and a test can assert which thread came back instead of asserting
 * that some string starting with "thread-" exists.
 */
export function makeFreshThread(now: number = Date.now()): PersistedThread {
  return {
    id: `thread-${now}`,
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
    return { threads: [fresh], activeThreadId: fresh.id, mintedFresh: true };
  }

  // If the stored active id no longer points at a thread, fall back to the first.
  if (!threads.some((t) => t.id === activeThreadId)) {
    activeThreadId = threads[0].id;
  }

  return { threads, activeThreadId, mintedFresh: false };
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


/** One row of `GET /conversations` (server/api/conversations.py). */
export interface ServerConversation {
  conversation_id: string;
  title: string;
  message_count: number;
  last_at?: string | null;
}

/**
 * Fold the server's conversation list into the locally-remembered one.
 *
 * 🔴 Gate item ⑦. localStorage used to be the ONLY record of which
 * conversations existed — the frontend mints the id and every server endpoint
 * takes it as a path parameter. In the packaged app that record does not
 * survive a restart: the sidecar took an ephemeral port each launch, the window
 * origin changed with it, and WebKit partitions localStorage by origin. The
 * messages were always safe in `arslan_messages`; nothing could name them.
 *
 * Who wins what, and why:
 *   - the SERVER owns which conversations EXIST (that is the recovery);
 *   - localStorage owns TITLES it already has, because the user may have
 *     renamed a thread and the server's title is a raw opening line;
 *   - a locally-known thread the server has not seen is KEPT, not dropped — a
 *     brand-new session has no messages yet, so it is legitimately absent
 *     server-side, and replacing the list would delete it before its first word.
 *
 * Fail-open: an empty server list changes nothing. A backend still booting must
 * never render as "you have no conversations".
 */
export function mergeServerConversations<T extends ThreadLike>(
  stored: T[],
  server: ServerConversation[],
): (T | PersistedThread)[] {
  if (!server.length) return stored;

  const known = new Map(stored.map((t) => [t.id, t]));
  const recency = new Map(server.map((c) => [c.conversation_id, c.last_at ?? ""]));

  const merged = server.map((c) => {
    const local = known.get(c.conversation_id);
    // 🔴 A thread already in memory is returned AS IS apart from its title.
    // Rebuilding it would replace `history` with [] — and for the thread the
    // user is currently looking at, that is the visible conversation going
    // blank. Only threads the client has never heard of are constructed here.
    if (local) return { ...local, title: local.title || c.title || "New Session" };
    return {
      id: c.conversation_id,
      title: c.title || "New Session",
      history: [] as [],
    } satisfies PersistedThread;
  });
  merged.sort((a, b) => (recency.get(b.id) ?? "").localeCompare(recency.get(a.id) ?? ""));

  // Threads the server has never seen (no messages yet) stay at the front:
  // one of them is usually the empty session the user is looking at.
  const unseen = stored.filter((t) => !recency.has(t.id));
  return [...unseen, ...merged];
}

/**
 * First-run gate — decides whether the onboarding wizard should be shown and
 * persists a "seen" flag so it only appears once.
 *
 * The wizard shows when: the provider-config list has finished loading (ready),
 * the user has NO provider/model configured yet (hasProvider === false), and
 * they haven't already seen/dismissed the wizard (seen === false). This is the
 * same "no model" condition that drives NoModelHint, but the wizard is the
 * richer first-touch experience; NoModelHint remains the quiet inline nudge for
 * every subsequent visit.
 */

const KEY = "arslan_first_run_seen";

export function getFirstRunSeen(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setFirstRunSeen(): void {
  try {
    localStorage.setItem(KEY, "1");
  } catch {
    /* storage disabled — the in-memory App flag still hides it this session */
  }
}

/** Backend state survives loopback-port changes; migrate the legacy local hint. */
export async function restoreFirstRunSeen(
  persisted: boolean | undefined,
  save: () => Promise<unknown>,
): Promise<boolean> {
  if (persisted === true) {
    setFirstRunSeen();
    return true;
  }
  const legacySeen = getFirstRunSeen();
  if (legacySeen) await save().catch(() => {});
  return legacySeen;
}

export function firstRunShouldShow(p: {
  ready: boolean;
  hasProvider: boolean;
  seen: boolean;
}): boolean {
  return p.ready && !p.hasProvider && !p.seen;
}

/**
 * 0.1.60: what the first run turned on, so the empty conversation can offer a first thing to try
 * for each (spec 2026-10-11-0160-first-run §2). Best effort: no storage, no suggestions.
 */
const TASKS_KEY = "arslan_first_tasks";
/** Fired when the first run records its choices, so an already-open chat shows them. */
export const FIRST_TASKS_EVENT = "arslan:first-tasks";
export interface FirstTasks { folders: boolean; hands: boolean }

export function recordFirstTasks(on: FirstTasks): void {
  try {
    localStorage.setItem(TASKS_KEY, JSON.stringify(on));
  } catch {
    /* storage disabled — no suggestions */
  }
  window.dispatchEvent(new Event(FIRST_TASKS_EVENT));
}

export function readFirstTasks(): FirstTasks | null {
  try {
    const raw = localStorage.getItem(TASKS_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    return { folders: v?.folders === true, hands: v?.hands === true };
  } catch {
    return null;
  }
}

export function clearFirstTasks(): void {
  try {
    localStorage.removeItem(TASKS_KEY);
  } catch {
    /* nothing to clear */
  }
}

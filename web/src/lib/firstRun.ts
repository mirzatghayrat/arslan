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

export function firstRunShouldShow(p: {
  ready: boolean;
  hasProvider: boolean;
  seen: boolean;
}): boolean {
  return p.ready && !p.hasProvider && !p.seen;
}

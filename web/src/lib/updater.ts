/** Bridge to the desktop shell's updater (desktop/src-tauri/src/lib.rs).
 *
 * The SPA is served over http://127.0.0.1 by the sidecar, so Tauri IPC exists
 * only when the shell granted it (capabilities/remote-ui-drag.json). In a
 * plain browser `__TAURI_INTERNALS__` is absent and every call here no-ops —
 * that absence IS the feature switch for the update pill. */

export type UpdateStatus = {
  /** "none" | "available" | "downloading" | "error" */
  state: string;
  version: string;
  error: string;
};

type TauriInternals = {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
};

function tauri(): TauriInternals | null {
  return (window as unknown as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__ ?? null;
}

export function updaterAvailable(): boolean {
  return tauri() !== null;
}

export async function fetchUpdateStatus(): Promise<UpdateStatus | null> {
  try {
    return ((await tauri()?.invoke("update_status")) as UpdateStatus) ?? null;
  } catch {
    return null;
  }
}

/** User clicked Install: the shell downloads, verifies, installs, restarts. */
export async function requestInstall(): Promise<void> {
  try {
    await tauri()?.invoke("install_update");
  } catch {
    // surfaced via the next update_status poll ("error" state)
  }
}

/** Push-path for status changes. The check takes 1-3s and the poll runs every
 * 60s, so without this the "checking" state would end between two polls and the
 * menu item would still feel dead — the event is the feature, not a speedup.
 * Returns an unsubscribe; resolves to a no-op in a plain browser, same switch
 * as everything above. */
export function subscribeUpdateStatus(cb: (s: UpdateStatus) => void): () => void {
  if (!updaterAvailable()) return () => {};
  let dead = false;
  let unlisten: (() => void) | null = null;
  import("@tauri-apps/api/event")
    .then(({ listen }) => listen<UpdateStatus>("update-status", (e) => cb(e.payload)))
    .then((un) => { if (dead) un(); else unlisten = un; })
    .catch(() => { /* capability missing — the poll still covers everything else */ });
  return () => { dead = true; unlisten?.(); };
}

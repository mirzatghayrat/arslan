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

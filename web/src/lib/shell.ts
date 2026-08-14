/** Ask the desktop shell to open a URL in the user's default browser.
 *
 * Same feature switch as lib/updater.ts: `__TAURI_INTERNALS__` absent means a
 * plain browser, and everything here quietly no-ops (the page can just use a
 * normal link there). The shell enforces ruling ③A's https-only rule on its
 * side — this wrapper is a doorway, not the guard. */

type TauriInternals = {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
};

function tauri(): TauriInternals | null {
  return (window as unknown as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__ ?? null;
}

export function shellAvailable(): boolean {
  return tauri() !== null;
}

export async function openExternal(url: string): Promise<void> {
  try {
    await tauri()?.invoke("open_external", { url });
  } catch {
    // The shell refused (non-https) or could not spawn a browser. The caller
    // surfaces flow-level failures; a throwing doorway would just crash UI.
  }
}

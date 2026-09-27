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

export async function createBackup(): Promise<boolean> {
  try {
    const shell = tauri();
    if (!shell) return false;
    await shell.invoke("create_backup");
    return true;
  } catch {
    return false;
  }
}

export async function openExternal(url: string): Promise<boolean> {
  try {
    const shell = tauri();
    if (!shell) return false;
    await shell.invoke("open_external", { url });
    return true;
  } catch {
    // The shell refused (non-https) or could not spawn a browser. The caller
    // surfaces flow-level failures; a throwing doorway would just crash UI.
    return false;
  }
}

/** The desktop shell asks to open a conversation after its notification was
 * clicked (0.1.41 resident mode). Returns an unsubscribe; a no-op in a plain
 * browser. Only a known conversation is opened — the id is data, not a route. */
export function subscribeOpenConversation(cb: (conversationId: string) => void): () => void {
  if (!shellAvailable()) return () => {};
  let dead = false;
  let unlisten: (() => void) | null = null;
  import("@tauri-apps/api/event")
    .then(({ listen }) => listen<string>("open-conversation", (event) => {
      if (typeof event.payload === "string" && event.payload) cb(event.payload);
    }))
    .then((un) => { if (dead) un(); else unlisten = un; })
    .catch(() => { /* capability missing: the window still opens, it just stays where it was */ });
  return () => { dead = true; unlisten?.(); };
}

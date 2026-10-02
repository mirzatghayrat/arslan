/**
 * The island page's doorway to the desktop shell (desktop/src-tauri/src/island.rs).
 * In a plain browser (dev) every call quietly no-ops and the page uses defaults.
 */
import type { ScreenGeometry } from './islandMachine';

type TauriInternals = { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };

declare global {
  interface Window {
    __ARSLAN_ISLAND_GEOMETRY__?: ScreenGeometry;
  }
}

function tauri(): TauriInternals | null {
  return (window as unknown as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__ ?? null;
}

export const inShell = () => tauri() !== null;

/** The geometry the shell measured when it built the window; a notched default in a browser. */
export function initialGeometry(): ScreenGeometry {
  const g = window.__ARSLAN_ISLAND_GEOMETRY__;
  if (isGeometry(g)) return g;
  return { notch: true, notchWidth: 200, barHeight: 32 };
}

export function isGeometry(g: unknown): g is ScreenGeometry {
  const v = g as ScreenGeometry | null | undefined;
  return !!v && typeof v.notch === 'boolean' && v.barHeight > 0 && (!v.notch || v.notchWidth > 0);
}

/** Tell the shell which rectangle takes the pointer; everywhere else clicks through. */
export function reportShape(r: { x: number; y: number; w: number; h: number }): void {
  tauri()?.invoke('island_shape', r).catch(() => { /* older shell: the window stays as it is */ });
}

export function openConversation(conversationId: string | null): void {
  tauri()?.invoke('island_open_conversation', { conversationId }).catch(() => {});
}

export function listenShell<T>(event: string, cb: (payload: T) => void): () => void {
  if (!inShell()) return () => {};
  let dead = false;
  let unlisten: (() => void) | null = null;
  import('@tauri-apps/api/event')
    .then(({ listen }) => listen<T>(event, (e) => cb(e.payload)))
    .then((un) => { if (dead) un(); else unlisten = un; })
    .catch(() => {});
  return () => { dead = true; unlisten?.(); };
}

/**
 * Injected-token bootstrap.
 *
 * Convention: a packaged/desktop build (Tauri, S4) that already knows the
 * server's bearer token injects it as a global `window.__ARSLAN_TOKEN__`
 * (a string) BEFORE the app bundle runs — e.g. via Tauri's
 * `initialization_scripts` / `window.eval("window.__ARSLAN_TOKEN__='…'" )`.
 *
 * We chose the window-global convention over a `<meta name="arslan-token">`
 * tag because the packaged shell already controls the JS execution context and
 * a global is trivially set from the native side without templating index.html.
 *
 * On app load we read it once and, if the auth store has no token yet, hydrate
 * the store so the very first API/WS call is already authenticated. In dev the
 * global is absent, so this is a harmless no-op.
 */

import { useAuthStore } from "../stores/authStore";

declare global {
  interface Window {
    __ARSLAN_TOKEN__?: string;
  }
}

export function bootstrapInjectedToken(): void {
  try {
    const injected = window.__ARSLAN_TOKEN__;
    if (typeof injected === "string" && injected.trim() && !useAuthStore.getState().token) {
      useAuthStore.getState().setToken(injected.trim());
    }
  } catch {
    /* non-browser / storage-disabled — ignore */
  }
}

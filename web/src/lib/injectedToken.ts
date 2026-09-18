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
 * On app load the native token takes precedence over the origin-local cache:
 * the backend token can change while the webview retains its old storage.
 * Hydrate before the first API/WS call. In dev the global is absent, so browser
 * credentials remain untouched.
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
    if (typeof injected === "string" && injected.trim()) {
      useAuthStore.getState().setToken(injected.trim());
    }
  } catch {
    /* non-browser / storage-disabled — ignore */
  }
}

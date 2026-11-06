import "@testing-library/jest-dom";
import { vi } from "vitest";

// Recent Node versions expose their own Web Storage globals. Vitest keeps
// pre-existing globals when populating jsdom, so bare localStorage can otherwise
// refer to Node's unconfigured file-backed object instead of browser storage.
// Use the actual per-environment jsdom objects, not a permissive storage mock.
// Vitest aliases window to globalThis; its `jsdom` handle retains the real window.
const browserWindow = (globalThis as unknown as { jsdom: { window: Window } }).jsdom.window;
for (const name of ["localStorage", "sessionStorage"] as const) {
  Object.defineProperty(globalThis, name, {
    configurable: true, enumerable: true, writable: true,
    value: browserWindow[name],
  });
}

// jsdom does not implement ResizeObserver. Provide a no-op stub so components
// that use it (e.g. stick-to-bottom scroll) don't crash in tests.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom has no Worker, and a window always does. This one gives up at once, so a fence stays plain text, as it does when a
// real worker gives up, with no budget timer left running. fmt1-code-block.test.tsx has one that really highlights.
vi.stubGlobal("Worker", class {
  onmessage: ((event: { data: null }) => void) | null = null;
  onerror: (() => void) | null = null;
  postMessage() { this.onmessage?.({ data: null }); }
  terminate() {}
});

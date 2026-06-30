import "@testing-library/jest-dom";

// jsdom does not implement ResizeObserver. Provide a no-op stub so components
// that use it (e.g. stick-to-bottom scroll) don't crash in tests.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

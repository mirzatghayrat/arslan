import "@testing-library/jest-dom";

// Node 22+/25 ships a native `localStorage` global that throws unless
// `--localstorage-file` is configured, and it shadows jsdom's implementation
// (on both `globalThis` and `window`). Install a working in-memory Storage
// polyfill so persisted-state stores can be unit-tested under jsdom.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const memoryStorage = new MemoryStorage();
const define = (target: object): void => {
  Object.defineProperty(target, "localStorage", {
    value: memoryStorage,
    writable: true,
    configurable: true,
  });
};

define(globalThis);
if (typeof window !== "undefined") {
  define(window);
}

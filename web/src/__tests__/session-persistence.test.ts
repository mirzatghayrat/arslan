/**
 * Unit tests for sessionPersistence.ts — the resume-last-conversation +
 * fresh-session-flag helpers. Pure logic over localStorage / sessionStorage
 * (jsdom provides both).
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  persistThreads,
  restoreThreads,
  consumeFreshSessionFlag,
  THREADS_KEY,
  ACTIVE_THREAD_KEY,
  SESSION_KEY,
} from "../lib/sessionPersistence";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("persist/restore round-trip", () => {
  it("round-trips threads + activeThreadId, dropping history", () => {
    const threads = [
      { id: "thread-1", title: "Quarterly report", history: [{ id: "m1" }], memberSpawnIds: ["3"] },
      { id: "thread-2", title: "New Session", history: [], memberSpawnIds: [] },
    ];
    persistThreads(threads, "thread-2");

    const restored = restoreThreads();
    expect(restored.activeThreadId).toBe("thread-2");
    expect(restored.threads).toHaveLength(2);
    expect(restored.threads[0].id).toBe("thread-1");
    expect(restored.threads[0].title).toBe("Quarterly report");
    expect(restored.threads[0].memberSpawnIds).toEqual(["3"]);
    // history is never persisted — always restored as []
    expect(restored.threads[0].history).toEqual([]);
    expect(restored.threads[1].history).toEqual([]);
  });

  it("persists the slim shape (no message history) in localStorage", () => {
    persistThreads(
      [{ id: "t", title: "T", history: [{ id: "m" }, { id: "m2" }] }],
      "t",
    );
    const raw = JSON.parse(localStorage.getItem(THREADS_KEY)!);
    expect(raw[0].history).toEqual([]);
    expect(localStorage.getItem(ACTIVE_THREAD_KEY)).toBe("t");
  });
});

describe("restoreThreads first-run / fallback", () => {
  it("returns one fresh 'New Session' when nothing is stored (no thread-default)", () => {
    const r = restoreThreads();
    expect(r.threads).toHaveLength(1);
    expect(r.threads[0].title).toBe("New Session");
    expect(r.threads[0].id).toMatch(/^thread-\d+$/);
    expect(r.threads[0].id).not.toBe("thread-default");
    expect(r.activeThreadId).toBe(r.threads[0].id);
  });

  it("falls back to the first thread when the stored active id is dangling", () => {
    localStorage.setItem(
      THREADS_KEY,
      JSON.stringify([{ id: "thread-a", title: "A", history: [] }]),
    );
    localStorage.setItem(ACTIVE_THREAD_KEY, "thread-gone");
    const r = restoreThreads();
    expect(r.activeThreadId).toBe("thread-a");
  });

  it("returns a fresh thread when the stored JSON is corrupt", () => {
    localStorage.setItem(THREADS_KEY, "{not json");
    const r = restoreThreads();
    expect(r.threads).toHaveLength(1);
    expect(r.threads[0].title).toBe("New Session");
  });
});

describe("consumeFreshSessionFlag", () => {
  it("is true once on a brand-new session, false thereafter", () => {
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
    expect(consumeFreshSessionFlag()).toBe(true); // first call: fresh
    expect(sessionStorage.getItem(SESSION_KEY)).toBe("1");
    expect(consumeFreshSessionFlag()).toBe(false); // same session: not fresh
    expect(consumeFreshSessionFlag()).toBe(false);
  });
});

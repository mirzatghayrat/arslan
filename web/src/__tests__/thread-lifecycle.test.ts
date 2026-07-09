/**
 * Unit tests for firstLiveThread — the shared archive/delete selection decision.
 * Guards the "archive/delete the ONLY live thread → mint a fresh session" edge:
 * when no non-archived thread other than the mutated one remains, the helper
 * returns null so the caller mints a fresh "New Session" instead of leaving an
 * archived-but-active thread in the main pane.
 */
import { describe, it, expect } from "vitest";
import { firstLiveThread } from "../lib/threadLifecycle";

describe("firstLiveThread", () => {
  it("returns null when the mutated thread is the only non-archived one (archive the last live thread)", () => {
    const threads = [
      { id: "a" }, // the thread being archived/deleted
      { id: "b", archived: true },
    ];
    expect(firstLiveThread(threads, "a")).toBeNull();
  });

  it("returns null when the list is empty after removal", () => {
    expect(firstLiveThread([], "gone")).toBeNull();
  });

  it("picks the first remaining non-archived thread, skipping the mutated one", () => {
    const threads = [{ id: "a" }, { id: "b" }, { id: "c" }];
    expect(firstLiveThread(threads, "a")?.id).toBe("b");
  });

  it("skips archived threads when choosing the next active", () => {
    const threads = [{ id: "a" }, { id: "b", archived: true }, { id: "c" }];
    expect(firstLiveThread(threads, "a")?.id).toBe("c");
  });

  it("never re-selects the mutated thread even if it is still non-archived in the snapshot", () => {
    // archive path passes the PRE-update snapshot (mutated thread still archived:false)
    const threads = [{ id: "a", archived: false }];
    expect(firstLiveThread(threads, "a")).toBeNull();
  });
});

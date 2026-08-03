/**
 * What the app opens on, and what it cleans up afterwards.
 *
 * Both functions under test are pure and take their world as arguments, which
 * is the only reason this is assertable at all: the behaviour they encode
 * happens across a process restart, and every failure mode is silent. An app
 * that reuses last week's conversation instead of opening a new one looks
 * exactly like one that works, right up until someone's next message lands in
 * the middle of an old thread.
 *
 * Every rule is tested from BOTH sides. A prune that drops nothing and a prune
 * that drops everything are equally broken, and only one of them is loud.
 */
import { describe, expect, it } from "vitest";

import { planBoot, pruneEmptyThreads } from "../lib/bootSession";
import type { PersistedThread, RestoredThreads } from "../lib/sessionPersistence";

const NOW = 1_700_000_000_000;

function thread(id: string, extra: Partial<PersistedThread> = {}): PersistedThread {
  return { id, title: id, history: [], ...extra };
}

function restored(
  threads: PersistedThread[],
  activeThreadId: string,
  mintedFresh = false,
): RestoredThreads {
  return { threads, activeThreadId, mintedFresh };
}

describe("planBoot", () => {
  it("opens a brand-new session on a real app launch", () => {
    const plan = planBoot(restored([thread("old-a"), thread("old-b")], "old-b"), {
      freshLaunch: true,
      now: NOW,
    });

    expect(plan.minted).toBe(true);
    expect(plan.activeThreadId).toBe(`thread-${NOW}`);
    // The id is a function of the injected clock, so this asserts WHICH thread
    // came back rather than that something vaguely thread-shaped exists.
    expect(plan.threads[0].id).toBe(`thread-${NOW}`);
  });

  it("keeps every existing thread when it opens the new one", () => {
    const plan = planBoot(restored([thread("old-a"), thread("old-b")], "old-b"), {
      freshLaunch: true,
      now: NOW,
    });

    // Opening a new session must not be a way to lose the old ones — the
    // sidebar is the whole recovery story for gate item ⑦.
    expect(plan.threads.map((t) => t.id)).toEqual([`thread-${NOW}`, "old-a", "old-b"]);
  });

  it("puts the opened session first, where the server merge also puts unseen threads", () => {
    const plan = planBoot(restored([thread("old-a")], "old-a"), { freshLaunch: true, now: NOW });
    expect(plan.threads[0].id).toBe(plan.activeThreadId);
  });

  it("does NOT mint a second empty session when restore already invented one", () => {
    // Clean install, or the packaged app's origin partition changing under it:
    // restoreThreads had to invent a thread, and that thread already IS a new
    // empty session. Minting beside it shows two of them on a first run.
    const invented = thread("thread-invented");
    const plan = planBoot(restored([invented], invented.id, true), {
      freshLaunch: true,
      now: NOW,
    });

    expect(plan.minted).toBe(false);
    expect(plan.threads).toHaveLength(1);
    expect(plan.activeThreadId).toBe(invented.id);
  });

  it("leaves a same-tab reload exactly where it was", () => {
    // The other side of the rule. Refreshing the page is not launching the app,
    // and yanking someone out of what they are reading would be a bug.
    const before = restored([thread("old-a"), thread("old-b")], "old-b");
    const plan = planBoot(before, { freshLaunch: false, now: NOW });

    expect(plan.minted).toBe(false);
    expect(plan.activeThreadId).toBe("old-b");
    expect(plan.threads.map((t) => t.id)).toEqual(["old-a", "old-b"]);
  });
});

describe("pruneEmptyThreads", () => {
  const serverIds = new Set(["has-messages"]);

  it("drops a session that was opened, never used, and left behind", () => {
    const kept = pruneEmptyThreads(
      [thread("stale-empty"), thread("has-messages")],
      { serverIds, activeThreadId: "has-messages" },
    );

    expect(kept.map((t) => t.id)).toEqual(["has-messages"]);
  });

  it("keeps the session the user is sitting in, even with nothing typed yet", () => {
    // Without this exemption, launching would delete the new session before its
    // first word — the feature would eat its own output.
    const kept = pruneEmptyThreads(
      [thread("just-opened"), thread("has-messages")],
      { serverIds, activeThreadId: "just-opened" },
    );

    expect(kept.map((t) => t.id)).toContain("just-opened");
  });

  it("keeps an archived thread the server has never heard of", () => {
    // Archiving is a deliberate act. An empty thread someone chose to keep is
    // not litter, and it is invisible in the main list — so deleting it would
    // be both wrong and unnoticed.
    const kept = pruneEmptyThreads(
      [thread("archived-empty", { archived: true }), thread("has-messages")],
      { serverIds, activeThreadId: "has-messages" },
    );

    expect(kept.map((t) => t.id)).toContain("archived-empty");
  });

  it("keeps every thread the server knows, whichever one is active", () => {
    const kept = pruneEmptyThreads(
      [thread("has-messages"), thread("other-real")],
      { serverIds: new Set(["has-messages", "other-real"]), activeThreadId: "has-messages" },
    );

    expect(kept).toHaveLength(2);
  });

  it("drops nothing when all three exemptions apply at once", () => {
    // The two-sided case for the whole predicate: given one of each protected
    // kind, a prune that is too eager shows up here and nowhere else.
    const kept = pruneEmptyThreads(
      [
        thread("active-empty"),
        thread("archived-empty", { archived: true }),
        thread("has-messages"),
      ],
      { serverIds, activeThreadId: "active-empty" },
    );

    expect(kept.map((t) => t.id)).toEqual([
      "active-empty",
      "archived-empty",
      "has-messages",
    ]);
  });

  it("preserves order so the sidebar does not reshuffle under the cursor", () => {
    const kept = pruneEmptyThreads(
      [thread("a"), thread("stale-empty"), thread("b")],
      { serverIds: new Set(["a", "b"]), activeThreadId: "a" },
    );

    expect(kept.map((t) => t.id)).toEqual(["a", "b"]);
  });
});

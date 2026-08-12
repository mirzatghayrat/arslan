/**
 * Unit tests for the autoTitle helpers (web/src/lib/autoTitle.ts).
 *
 * Tests are pure — no React, no DOM needed.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { shouldAutoTitle, maybeAutoTitle, seedTitledThreadIds } from "../lib/autoTitle";
import type { Message } from "../types";

// ── Minimal message factories ────────────────────────────────────────────────

function userMsg(text = "Hello"): Message {
  return {
    id: `u-${Math.random()}`,
    sender: "user",
    senderName: "User",
    senderAvatar: "",
    text,
    timestamp: "",
  };
}

function assistantMsg(text = "Hi there!"): Message {
  return {
    id: `a-${Math.random()}`,
    sender: "arslan",
    senderName: "Arslan",
    senderAvatar: "🦁",
    text,
    timestamp: "",
  };
}

function spawnMsg(text = "Spawn reply"): Message {
  return {
    id: `s-${Math.random()}`,
    sender: "spawn",
    senderName: "Spawn",
    senderAvatar: "🤖",
    text,
    timestamp: "",
  };
}

// ── shouldAutoTitle ──────────────────────────────────────────────────────────

describe("shouldAutoTitle", () => {
  it("returns false for an empty history", () => {
    expect(shouldAutoTitle({ title: "New Session", history: [] })).toBe(false);
  });

  it("returns false when there is only a user message (no assistant reply yet)", () => {
    expect(
      shouldAutoTitle({ title: "New Session", history: [userMsg()] }),
    ).toBe(false);
  });

  it("returns true when exactly one user message + one arslan reply", () => {
    expect(
      shouldAutoTitle({
        title: "Orchestration thread #1",
        history: [userMsg(), assistantMsg()],
      }),
    ).toBe(true);
  });

  it("returns true when the assistant reply is from a spawn", () => {
    expect(
      shouldAutoTitle({
        title: "New Session",
        history: [userMsg(), spawnMsg()],
      }),
    ).toBe(true);
  });

  it("returns false when there are two user messages (not the first exchange)", () => {
    expect(
      shouldAutoTitle({
        title: "some title",
        history: [userMsg(), assistantMsg(), userMsg("Second question")],
      }),
    ).toBe(false);
  });

  it("returns false when history has two user messages even with assistant reply", () => {
    expect(
      shouldAutoTitle({
        title: "some title",
        history: [userMsg(), assistantMsg(), userMsg(), assistantMsg()],
      }),
    ).toBe(false);
  });

  it("returns true with multiple assistant replies (only first exchange matters)", () => {
    // One user message + multiple assistant replies — still the first exchange
    expect(
      shouldAutoTitle({
        title: "New Session",
        history: [userMsg(), assistantMsg(), assistantMsg("follow-up from spawn")],
      }),
    ).toBe(true);
  });
});

// ── maybeAutoTitle ───────────────────────────────────────────────────────────

describe("maybeAutoTitle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls generate with firstMessage and firstReply and invokes onTitle with the result", async () => {
    const generate = vi.fn().mockResolvedValue({ title: "Generated Title" });
    const onTitle = vi.fn();

    const history: Message[] = [userMsg("User question"), assistantMsg("Assistant answer")];

    await maybeAutoTitle("thread-1", { history }, generate, onTitle);

    expect(generate).toHaveBeenCalledOnce();
    expect(generate).toHaveBeenCalledWith("User question", "Assistant answer");
    expect(onTitle).toHaveBeenCalledOnce();
    expect(onTitle).toHaveBeenCalledWith("thread-1", "Generated Title");
  });

  it("passes the correct threadId to onTitle even if multiple threads are active", async () => {
    const generate = vi.fn().mockResolvedValue({ title: "Thread Title" });
    const onTitle = vi.fn();

    await maybeAutoTitle("thread-abc", { history: [userMsg(), assistantMsg()] }, generate, onTitle);

    expect(onTitle).toHaveBeenCalledWith("thread-abc", "Thread Title");
  });

  it("does NOT call onTitle when generate rejects (graceful fallback)", async () => {
    const generate = vi.fn().mockRejectedValue(new Error("network error"));
    const onTitle = vi.fn();

    await maybeAutoTitle("thread-1", { history: [userMsg(), assistantMsg()] }, generate, onTitle);

    expect(generate).toHaveBeenCalledOnce();
    expect(onTitle).not.toHaveBeenCalled();
  });

  it("does NOT call onTitle when generate returns empty title", async () => {
    const generate = vi.fn().mockResolvedValue({ title: "" });
    const onTitle = vi.fn();

    await maybeAutoTitle("thread-1", { history: [userMsg(), assistantMsg()] }, generate, onTitle);

    expect(onTitle).not.toHaveBeenCalled();
  });

  it("calls generate with only firstMessage when there is no assistant reply", async () => {
    const generate = vi.fn().mockResolvedValue({ title: "Title" });
    const onTitle = vi.fn();

    // history has no assistant message — firstReply will be undefined
    await maybeAutoTitle("thread-1", { history: [userMsg("Only user msg")] }, generate, onTitle);

    expect(generate).toHaveBeenCalledWith("Only user msg", undefined);
    expect(onTitle).toHaveBeenCalledWith("thread-1", "Title");
  });

  it("handles history with no user message gracefully (does not call generate)", async () => {
    const generate = vi.fn();
    const onTitle = vi.fn();

    await maybeAutoTitle("thread-1", { history: [assistantMsg()] }, generate, onTitle);

    expect(generate).not.toHaveBeenCalled();
    expect(onTitle).not.toHaveBeenCalled();
  });
});


// ── seedTitledThreadIds ──────────────────────────────────────────────────────
//
// 🔴 THE BUG THIS PINS. App.tsx seeded the "already titled" set with EVERY
// restored thread id, on the stated assumption that "restored threads already
// have real titles". That is false for a thread still called "New Session" —
// and sessionPersistence hands back exactly that after a wipe and on a fresh
// install. The id went into the set, so when the first exchange completed the
// auto-title never fired, and the FIRST conversation of every new user kept the
// truncated user text as its name.
//
// The discriminating case is a restored thread WITH a placeholder title: seeding
// everything and seeding nothing both pass a test that only uses custom titles.

describe("seedTitledThreadIds", () => {
  it("seeds a thread that already has a real title", () => {
    const seeded = seedTitledThreadIds([{ id: "a", title: "Deploy pipeline notes" }]);
    expect(seeded.has("a")).toBe(true);
  });

  it("does NOT seed a thread still called New Session", () => {
    // The fresh-install case. Seeding it is what made the first conversation
    // permanently untitleable.
    const seeded = seedTitledThreadIds([{ id: "a", title: "New Session" }]);
    expect(seeded.has("a")).toBe(false);
  });

  it("does NOT seed an untouched orchestration thread", () => {
    const seeded = seedTitledThreadIds([{ id: "a", title: "Orchestration thread #3" }]);
    expect(seeded.has("a")).toBe(false);
  });

  it("keeps the two apart in one restore", () => {
    const seeded = seedTitledThreadIds([
      { id: "real", title: "Quarterly review" },
      { id: "fresh", title: "New Session" },
    ]);
    expect(seeded.has("real")).toBe(true);
    expect(seeded.has("fresh")).toBe(false);
  });

  it("seeds a thread whose title is the truncated first message", () => {
    // Deliberate: after the dumb rename we cannot tell a truncation from a title
    // the user typed, and overwriting someone's own name for a thread is worse
    // than leaving a plain one.
    const seeded = seedTitledThreadIds([{ id: "a", title: "how do I reset the…" }]);
    expect(seeded.has("a")).toBe(true);
  });

  it("treats a blank title as not yet titled", () => {
    const seeded = seedTitledThreadIds([{ id: "a", title: "   " }]);
    expect(seeded.has("a")).toBe(false);
  });
});

describe("App.tsx actually uses the seed helper", () => {
  it("does not seed the set from every restored id", async () => {
    // A pure helper nobody calls is a bug still shipping. The old line —
    // new Set(restoredInit.threads.map((t) => t.id)) — is what this forbids.
    const src = await import("../App?raw");
    const text = src.default as string;
    expect(text).toMatch(/seedTitledThreadIds\(restoredInit\.threads\)/);
    expect(text).not.toMatch(/new Set\(restoredInit\.threads\.map/);
  });
});

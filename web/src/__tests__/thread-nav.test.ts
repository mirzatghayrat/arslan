/** v0.1.7 regression: coming back to the conversation you are already on left
 * the chat blank until you switched away and back a second time. */
import { describe, expect, it } from "vitest";
import { threadNavAction } from "../lib/threadNav";

describe("threadNavAction", () => {
  it("does NOT reset the store when re-selecting the active thread", () => {
    // The store is only safe to wipe when a history frame is guaranteed to
    // follow — and it only follows when the socket URL changes.
    expect(threadNavAction("t1", "t1")).toEqual({ endPrevious: false, resetStore: false });
  });

  it("does NOT end a conversation that is not being left", () => {
    expect(threadNavAction("t1", "t1").endPrevious).toBe(false);
  });

  it("DOES reset and end when actually switching threads", () => {
    // Discrimination: a fix that never resets would pass the two tests above
    // and resurrect stale messages from the previous conversation.
    expect(threadNavAction("t1", "t2")).toEqual({ endPrevious: true, resetStore: true });
  });

  it("resets but ends nothing on the first selection of a session", () => {
    expect(threadNavAction(null, "t1")).toEqual({ endPrevious: false, resetStore: true });
    expect(threadNavAction("", "t1")).toEqual({ endPrevious: false, resetStore: true });
  });
});

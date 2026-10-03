/** Mobile bridge: a history row with source "phone" becomes a user message marked "from iPhone";
 *  every other source is the window. */
import { describe, it, expect } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";

describe("from iPhone", () => {
  it("only a phone source marks a user message", () => {
    useArslanStore.setState(initialArslanState(), true);
    useArslanStore.getState().handleFrame({ type: "history", messages: [
      { message_id: 1, role: "user", content: "find flights", spawn_id: null, source: "phone" },
      { message_id: 2, role: "user", content: "and hotels", spawn_id: null, source: null },
      { message_id: 3, role: "user", content: "x", spawn_id: null, source: "admin" },
      { message_id: 4, role: "arslan", content: "ok", spawn_id: null, source: "phone" },
    ] } as never);
    const messages = toUiMessages(useArslanStore.getState().items);
    expect(messages.map((m) => !!m.fromPhone)).toEqual([true, false, false, false]);
  });
});

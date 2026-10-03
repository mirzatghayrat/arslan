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
    const items = useArslanStore.getState().items;
    expect(items.map((i) => !!i.fromPhone)).toEqual([true, false, false, false]);   // never on Arslan's own replies
    const messages = toUiMessages(items);
    expect(messages.map((m) => !!m.fromPhone)).toEqual([true, false, false, false]);
  });
});

describe("the phone in an open window", () => {
  it("the phone's message arrives live, marked from iPhone", () => {
    useArslanStore.setState(initialArslanState(), true);
    const { handleFrame } = useArslanStore.getState();
    handleFrame({ type: "message", message_id: 7, content: "find flights", role: "user", source: "phone" } as never);
    handleFrame({ type: "message", message_id: 8, content: "typed here", role: "user" } as never);
    const items = useArslanStore.getState().items;
    expect(items.map((i) => [i.id, i.role, i.content, !!i.fromPhone]))
      .toEqual([[7, "user", "find flights", true], [8, "user", "typed here", false]]);
    expect(useArslanStore.getState().lastMessageId).toBe(8);
  });

  it("a card answered elsewhere closes here; another card stays", () => {
    useArslanStore.setState(initialArslanState(), true);
    const { handleFrame } = useArslanStore.getState();
    handleFrame({ type: "propose_run_command", call_id: "c1", pretty: "git push", reason: "" } as never);
    handleFrame({ type: "propose_schedule", call_id: "s1", name: "digest", when: "daily" } as never);
    handleFrame({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write", path: "a" } as never);
    handleFrame({ type: "propose_action", call_id: "a1", kind: "mac_shortcut", target: "t", detail: "" } as never);

    handleFrame({ type: "card_resolved", call_id: "elsewhere", outcome: "approved", by: "phone" } as never);
    let s = useArslanStore.getState();
    expect([s.pendingCommand?.callId, s.pendingSchedule?.callId, s.pendingWorkspaceWrite?.callId, s.pendingAction?.callId])
      .toEqual(["c1", "s1", "w1", "a1"]);

    handleFrame({ type: "card_resolved", call_id: "c1", outcome: "approved", by: "phone" } as never);
    handleFrame({ type: "card_resolved", call_id: "w1", outcome: "expired" } as never);
    s = useArslanStore.getState();
    expect([s.pendingCommand, s.pendingWorkspaceWrite]).toEqual([null, null]);
    expect([s.pendingSchedule?.callId, s.pendingAction?.callId]).toEqual(["s1", "a1"]);

    handleFrame({ type: "card_resolved", call_id: "s1", outcome: "declined", by: "mac" } as never);
    handleFrame({ type: "card_resolved", call_id: "a1", outcome: "declined", by: "phone" } as never);
    s = useArslanStore.getState();
    expect([s.pendingSchedule, s.pendingAction]).toEqual([null, null]);
  });
});

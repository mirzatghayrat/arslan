/** 0.1.55 §5: four frames nothing rendered (suggest_create, suggest_update, propose_invite,
 *  propose_staffing) are gone from the store. An old server sending one changes nothing. */
import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState()));

describe("retired frames", () => {
  it.each(["suggest_create", "suggest_update", "propose_invite", "propose_staffing"])("%s is ignored", (type) => {
    const store = useArslanStore.getState();
    store.setThinking(true);
    const before = useArslanStore.getState();
    expect(() => store.handleFrame({ type, draft: {}, spawn_id: 1, reason: "r", candidates: [], create_draft: null } as never)).not.toThrow();
    const after = useArslanStore.getState();
    expect(after.items).toEqual(before.items);
    // Not a "responding" frame any more: it does not end the thinking state either.
    expect(after.thinking).toBe(true);
  });

  it("the store no longer carries their state", () => {
    const state = useArslanStore.getState() as unknown as Record<string, unknown>;
    for (const key of ["suggestion", "suggestionTaskBrief", "suggestionOverlaps", "pendingInvite", "pendingStaffing",
      "pendingUpdate", "dismissAllPending", "noteUserSend"]) {
      expect(state, key).not.toHaveProperty(key);
    }
  });
});

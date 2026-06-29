import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

describe("propose_staffing frame", () => {
  it("sets pendingStaffing with camelCase candidate and createDraft", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_staffing",
      candidates: [
        { spawn_id: 1, name: "小美", score: 0.6, why: "she has skill X" },
      ],
      create_draft: {
        name: "新分身",
        domain: "research",
        capabilities: ["web_search"],
      },
    } as any);

    const state = useArslanStore.getState() as any;
    const ps = state.pendingStaffing;
    expect(ps).not.toBeNull();
    expect(ps.candidates).toHaveLength(1);
    expect(ps.candidates[0].spawnId).toBe(1);
    expect(ps.candidates[0].name).toBe("小美");
    expect(ps.candidates[0].score).toBe(0.6);
    expect(ps.candidates[0].why).toBe("she has skill X");
    expect(ps.createDraft).toEqual({
      name: "新分身",
      domain: "research",
      capabilities: ["web_search"],
    });
  });

  it("null create_draft is stored as null", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_staffing",
      candidates: [{ spawn_id: 2, name: "Beta", score: 0.9, why: "best" }],
      create_draft: null,
    } as any);

    const ps = (useArslanStore.getState() as any).pendingStaffing;
    expect(ps).not.toBeNull();
    expect(ps.createDraft).toBeNull();
  });

  it("clearPendingStaffing resets to null", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_staffing",
      candidates: [{ spawn_id: 3, name: "Gamma", score: 0.5, why: "ok" }],
      create_draft: null,
    } as any);

    (useArslanStore.getState() as any).clearPendingStaffing();

    expect((useArslanStore.getState() as any).pendingStaffing).toBeNull();
  });

  it("pendingStaffing starts as null", () => {
    expect((useArslanStore.getState() as any).pendingStaffing).toBeNull();
  });
});

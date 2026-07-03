import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "./arslanStore";

describe("dismissAllPending", () => {
  beforeEach(() => {
    // Full-replace reset (keeps action methods intact) so each test starts clean.
    useArslanStore.setState(initialArslanState(), true);
  });

  it("clears all four proposal cards but not execution markers", () => {
    const s = useArslanStore.getState();
    // Seed the four user-facing proposal cards via handleFrame.
    s.handleFrame({ type: "suggest_create", draft: { name: "X" }, task_brief: "t", overlaps: null } as any);
    s.handleFrame({ type: "propose_invite", spawn_id: 1, reason: "r" } as any);
    s.handleFrame({ type: "propose_staffing", candidates: [], create_draft: null } as any);
    // suggest_update: seed directly to avoid depending on its full frame shape.
    useArslanStore.setState({
      pendingUpdate: { spawnId: 2, spawnName: "Y", current: {} as any, changes: {} as any, reason: "why" },
    });
    // Seed execution-phase markers that must survive.
    useArslanStore.setState({
      pendingRoute: { spawnId: 3, spawnName: "Z" },
      pendingProposalSpawnId: 4,
    });

    // Sanity: cards are present before dismiss.
    const before = useArslanStore.getState();
    expect(before.suggestion).not.toBeNull();
    expect(before.pendingInvite).not.toBeNull();
    expect(before.pendingStaffing).not.toBeNull();
    expect(before.pendingUpdate).not.toBeNull();

    useArslanStore.getState().dismissAllPending();

    const st = useArslanStore.getState();
    // All four proposal cards cleared.
    expect(st.suggestion).toBeNull();
    expect(st.suggestionTaskBrief).toBeNull();
    expect(st.suggestionOverlaps).toBeNull();
    expect(st.pendingInvite).toBeNull();
    expect(st.pendingStaffing).toBeNull();
    expect(st.pendingUpdate).toBeNull();
    // Execution-phase markers untouched.
    expect(st.pendingRoute).not.toBeNull();
    expect(st.pendingProposalSpawnId).toBe(4);
  });
});

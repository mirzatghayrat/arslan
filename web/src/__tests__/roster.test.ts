import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState({ roster: [] } as any));

it("applies roster_update to the store", () => {
  useArslanStore.getState().handleFrame({
    type: "roster_update",
    members: [{ spawn_id: 4, spawn_name: "领英智囊", joined_via: "routed", status: "idle" }],
  } as any);
  const roster = (useArslanStore.getState() as any).roster;
  expect(roster).toHaveLength(1);
  expect(roster[0].spawnId).toBe(4);
  expect(roster[0].spawnName).toBe("领英智囊");
  expect(roster[0].status).toBe("idle");
});

it("replaces roster on a new roster_update (not append)", () => {
  useArslanStore.getState().handleFrame({ type: "roster_update", members: [{ spawn_id: 4, spawn_name: "a", joined_via: "routed", status: "idle" }] } as any);
  useArslanStore.getState().handleFrame({ type: "roster_update", members: [] } as any);
  expect((useArslanStore.getState() as any).roster).toEqual([]);
});

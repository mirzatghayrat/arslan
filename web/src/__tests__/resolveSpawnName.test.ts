import { describe, it, expect } from "vitest";
import { resolveSpawnName } from "../api/resolveSpawnName";

describe("resolveSpawnName", () => {
  it("resolves a numeric spawnId against numeric-id SpawnSummary list", () => {
    const spawns = [
      { id: 7, name: "Mermer" },
      { id: 9, name: "小美" },
    ];
    expect(resolveSpawnName(spawns, 7)).toBe("Mermer");
  });

  it("resolves a numeric spawnId against a string-id UI spawns list (the regression)", () => {
    // toUiSpawn stringifies ids; propose_invite.spawn_id is numeric. A naive
    // `s.id === spawnId` would be "7" === 7 → always false. This guards it.
    const uiSpawns = [
      { id: "7", name: "Mermer" },
      { id: "9", name: "小美" },
    ];
    expect(resolveSpawnName(uiSpawns, 7)).toBe("Mermer");
  });

  it("returns undefined when the id is not present", () => {
    expect(resolveSpawnName([{ id: 1, name: "A" }], 42)).toBeUndefined();
  });

  it("returns undefined for an empty list", () => {
    expect(resolveSpawnName([], 7)).toBeUndefined();
  });
});

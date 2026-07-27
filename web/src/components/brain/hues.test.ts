import { describe, expect, it } from "vitest";
import { hueIndex, hueVar } from "./hues";

describe("hues", () => {
  it("maps a key to a stable --hue-N var in 1..10", () => {
    const a = hueVar("identity"), b = hueVar("identity");
    expect(a).toBe(b); // stable across calls
    expect(a).toMatch(/^var\(--hue-([1-9]|10)\)$/);
    expect(hueVar("ft:pdf")).toMatch(/^var\(--hue-([1-9]|10)\)$/);
  });

  it("keeps every index within 1..10 for varied keys", () => {
    for (const k of ["identity", "communication", "interest", "task", "spawn_wish", "other",
                     "research", "engineering", "ft:pdf", "ft:url", "ft:image", ""]) {
      const idx = hueIndex(k);
      expect(idx).toBeGreaterThanOrEqual(1);
      expect(idx).toBeLessThanOrEqual(10);
    }
  });
});

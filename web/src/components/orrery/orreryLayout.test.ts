import { describe, it, expect } from "vitest";
import { layout, toXY, hash01 } from "./orreryLayout";

describe("orreryLayout", () => {
  it("is deterministic — same id yields same position", () => {
    const a = layout([{ id: "n1", cat: "source", label: "x" }])[0];
    const b = layout([{ id: "n1", cat: "source", label: "x" }])[0];
    expect(a.angle).toBe(b.angle);
    expect(a.rf).toBe(b.rf);
    expect(a.z).toBe(b.z);
  });
  it("hub sits at center with z=1", () => {
    const h = layout([{ id: "hub", cat: "hub", label: "YOU" }])[0];
    expect(h.rf).toBe(0);
    expect(h.z).toBe(1);
  });
  it("sources sit at a larger radius than spawns", () => {
    const s = layout([{ id: "s", cat: "source", label: "x" }])[0];
    const p = layout([{ id: "p", cat: "spawn", label: "y" }])[0];
    expect(s.rf).toBeGreaterThan(p.rf);
  });
  it("nodes land within their category angular band", () => {
    const p = layout([{ id: "p", cat: "spawn", label: "y" }])[0];
    expect(Math.abs(p.angle - (-Math.PI / 2))).toBeLessThan((46 * Math.PI) / 180);
  });
  it("hash01 is in [0,1)", () => {
    for (const s of ["a", "bb", "ccc"]) {
      const v = hash01(s);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
  it("toXY places outer nodes further from center", () => {
    const s = layout([{ id: "s", cat: "source", label: "x" }])[0];
    const { x, y } = toXY(s, 100, 100, 100);
    expect(Math.hypot(x - 100, y - 100)).toBeGreaterThan(50);
  });
});

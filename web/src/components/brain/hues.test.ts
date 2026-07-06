import { describe, expect, it } from "vitest";
import { hueIndex, hueVar } from "./hues";

describe("hues", () => {
  it("maps a key to a stable --hue-N var in 1..10", () => {
    const a = hueVar("身份背景"), b = hueVar("身份背景");
    expect(a).toBe(b); // stable across calls
    expect(a).toMatch(/^var\(--hue-([1-9]|10)\)$/);
    expect(hueVar("ft:pdf")).toMatch(/^var\(--hue-([1-9]|10)\)$/);
  });

  it("keeps every index within 1..10 for varied keys", () => {
    for (const k of ["身份背景", "沟通偏好", "领域兴趣", "任务需求", "想建的分身", "其他",
                     "research", "engineering", "ft:pdf", "ft:url", "ft:image", ""]) {
      const idx = hueIndex(k);
      expect(idx).toBeGreaterThanOrEqual(1);
      expect(idx).toBeLessThanOrEqual(10);
    }
  });
});

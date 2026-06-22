import { describe, it, expect } from "vitest";
import { contrastRatio, relLuminance } from "../theme/contrast";

it("computes luminance of black and white", () => {
  expect(relLuminance("#000000")).toBeCloseTo(0, 3);
  expect(relLuminance("#FFFFFF")).toBeCloseTo(1, 3);
});

it("black on white is 21:1", () => {
  expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 0);
});

it("flags a low-contrast pair", () => {
  expect(contrastRatio("#777777", "#808080")).toBeLessThan(4.5);
});

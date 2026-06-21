import { describe, it, expect } from "vitest";
import { PALETTE_TOKENS } from "../theme/palettes";
import { contrastRatio } from "../theme/contrast";

const AA_TEXT = 4.5;
const AA_LARGE = 3.0;

describe("every palette/mode meets WCAG AA", () => {
  for (const [id, modes] of Object.entries(PALETTE_TOKENS)) {
    for (const mode of ["light", "dark"] as const) {
      const t = modes[mode];
      it(`${id}/${mode}: foreground on background`, () => {
        expect(contrastRatio(t.foreground, t.background)).toBeGreaterThanOrEqual(AA_TEXT);
      });
      it(`${id}/${mode}: foreground on surface`, () => {
        expect(contrastRatio(t.foreground, t.surface)).toBeGreaterThanOrEqual(AA_TEXT);
      });
      it(`${id}/${mode}: muted on background`, () => {
        expect(contrastRatio(t.mutedForeground, t.background)).toBeGreaterThanOrEqual(AA_LARGE);
      });
      it(`${id}/${mode}: primary-foreground on primary`, () => {
        expect(contrastRatio(t.primaryForeground, t.primary)).toBeGreaterThanOrEqual(AA_LARGE);
      });
    }
  }
});

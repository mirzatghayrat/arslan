// web/src/__tests__/primary-token.test.ts
// Locks the `current` palette's deep-orange CTA (#D9741A) + white foreground,
// and re-verifies white-on-primary clears palette-contrast.test.ts's AA_LARGE (3.0) bar.
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { contrastRatio } from "../theme/contrast";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(resolve(here, "..", "theme", "tokens.css"), "utf8");

const PRIMARY = "#D9741A";
const FOREGROUND = "#FFFFFF";
const AA_LARGE = 3.0; // mirrors palette-contrast.test.ts

// Extract exactly the `current` DARK block (the `.dark, .dark[data-palette="current"] { ... }`
// arm). Do NOT match `ember` or any other data-palette block.
function currentDarkBlock(src: string): string {
  const start = src.indexOf(".dark[data-palette=\"current\"]");
  expect(start).toBeGreaterThan(-1);
  const open = src.indexOf("{", start);
  const close = src.indexOf("}", open);
  return src.slice(open, close);
}

describe("current palette primary CTA token", () => {
  const block = currentDarkBlock(css);

  it("current dark --primary is the deep orange", () => {
    expect(block).toMatch(new RegExp(`--primary:\\s*${PRIMARY}\\b`, "i"));
  });

  it("current dark --primary-foreground is white", () => {
    expect(block).toMatch(new RegExp(`--primary-foreground:\\s*${FOREGROUND}\\b`, "i"));
  });

  it("does not match the ember block", () => {
    expect(block).not.toMatch(/#F97316/i);
  });

  it("white-on-primary clears AA_LARGE (large/bold text)", () => {
    expect(contrastRatio(FOREGROUND, PRIMARY)).toBeGreaterThanOrEqual(AA_LARGE);
  });
});

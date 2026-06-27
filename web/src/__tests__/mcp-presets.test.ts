import { describe, it, expect } from "vitest";
import { MCP_PRESETS } from "../data/mcpPresets";

describe("MCP_PRESETS", () => {
  it("are well-formed curated stdio presets", () => {
    expect(MCP_PRESETS.length).toBeGreaterThanOrEqual(4);
    for (const p of MCP_PRESETS) {
      expect(p.label).toBeTruthy();
      expect(p.transport).toBe("stdio");
      expect(p.command).toBeTruthy();
      expect(Array.isArray(p.args)).toBe(true);
    }
    expect(MCP_PRESETS.some((p) => p.command === "npx")).toBe(true);
  });
});

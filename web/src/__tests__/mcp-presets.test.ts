import { describe, it, expect } from "vitest";
import { MCP_PRESETS, isOneClick } from "../data/mcpPresets";

describe("MCP_PRESETS", () => {
  it("are well-formed curated stdio presets", () => {
    expect(MCP_PRESETS.length).toBeGreaterThanOrEqual(4);
    for (const p of MCP_PRESETS) {
      expect(p.label).toBeTruthy();
      expect(p.transport).toBe("stdio");
      expect(p.command).toBeTruthy();
      expect(Array.isArray(p.args)).toBe(true);
      // every preset declares a runtime so the UI can hint node vs python(uv)
      expect(["node", "python"]).toContain(p.runtime);
      // node servers launch via npx, python servers via uvx — never crossed
      expect(p.command).toBe(p.runtime === "python" ? "uvx" : "npx");
    }
  });

  it("splits one-click (no creds) from prefill-only (needs a key)", () => {
    const oneClick = MCP_PRESETS.filter(isOneClick);
    const auth = MCP_PRESETS.filter((p) => !isOneClick(p));
    // one-click set includes the four zero-input servers the product ships
    for (const label of ["Fetch", "Memory", "Sequential Thinking", "Time"]) {
      const p = MCP_PRESETS.find((x) => x.label === label)!;
      expect(isOneClick(p)).toBe(true);
      expect(p.needsPath).toBeFalsy();
    }
    // path servers are one-click but flagged needsPath
    for (const label of ["Filesystem", "Git"]) {
      const p = MCP_PRESETS.find((x) => x.label === label)!;
      expect(isOneClick(p)).toBe(true);
      expect(p.needsPath).toBe(true);
    }
    // credentialed presets are prefill-only and carry envKeys
    expect(auth.map((p) => p.label).sort()).toEqual(["Brave Search", "GitHub"]);
    for (const p of auth) expect(p.envKeys!.length).toBeGreaterThan(0);
    expect(oneClick.length).toBeGreaterThan(auth.length);
  });
});

/**
 * Lockstep guard: the frontend's tool-transport table vs the backend's.
 *
 * `web/src/lib/toolTransport.ts` deliberately duplicates `NATIVE_TOOL_CALLS`
 * from `server/services/capability_fitness.py` instead of fetching it, because a
 * safety notice delivered over the network vanishes exactly when the network
 * does — and a vanished warning is the bug, not a degraded nicety.
 *
 * Duplication is only defensible with something that fails when the copies
 * drift, which is this. The specific rot it prevents: G1 lands, the Python table
 * flips `anthropic` to supported, and Settings keeps telling users their tools
 * are dead. Nothing errors; the app just lies in the other direction.
 *
 * This is a source-text assertion, and that is the right tool here — what is
 * being asserted IS "these two literals are equal". Nothing observable at
 * runtime connects a Python dict to a TypeScript one.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { TOOL_TRANSPORT, type ToolTransport } from "../lib/toolTransport";

const REPO = join(__dirname, "..", "..", "..");

/** Parse `NATIVE_TOOL_CALLS = { "openai": SUPPORTED, ... }` out of the module. */
function backendTable(): Record<string, ToolTransport> {
  const src = readFileSync(join(REPO, "server/services/capability_fitness.py"), "utf8");
  const block = src.match(/NATIVE_TOOL_CALLS:\s*dict\[str,\s*str\]\s*=\s*\{([\s\S]*?)\n\}/);
  if (!block) throw new Error("NATIVE_TOOL_CALLS not found — the backend module was restructured");

  const CONSTANTS: Record<string, ToolTransport> = {
    SUPPORTED: "supported",
    UNSUPPORTED: "unsupported",
    UNVERIFIED: "unverified",
  };
  const out: Record<string, ToolTransport> = {};
  for (const line of block[1].split("\n")) {
    // Strip trailing `# comment` first: the real entries carry explanatory ones.
    const m = line.replace(/#.*$/, "").match(/"([^"]+)"\s*:\s*([A-Z_]+)\s*,?/);
    if (!m) continue;
    const state = CONSTANTS[m[2]];
    if (!state) throw new Error(`unknown state constant ${m[2]} for provider ${m[1]}`);
    out[m[1]] = state;
  }
  return out;
}

describe("tool-transport table", () => {
  it("parses a non-trivial table out of the backend (the guard can see its subject)", () => {
    // Without this the whole file could pass against an empty parse — a test
    // that cannot see what it claims to check is not a test.
    const backend = backendTable();
    expect(Object.keys(backend).length).toBeGreaterThanOrEqual(4);
    expect(backend.anthropic).toBeDefined();
  });

  it("matches the backend exactly, provider for provider", () => {
    expect(TOOL_TRANSPORT).toEqual(backendTable());
  });

  it("still names a provider this notice exists for", () => {
    // A guard on equality alone would stay green if BOTH sides were emptied.
    //
    // This asserted anthropic too until G1 put tool schemas on the Anthropic wire.
    // The fact was updated and the guard kept: what it defends against is the two
    // tables being blanked or blanket-approved in lockstep, which equality alone
    // cannot see. Gemini carries that on its own now — when Gemini is fixed, this
    // needs a provider that genuinely drops tools, or it stops guarding anything.
    const backend = backendTable();
    expect(backend.gemini).toBe("unsupported");
    expect(backend.anthropic).toBe("supported");
  });
});

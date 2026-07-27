import { describe, expect, it } from "vitest";
import { toUiRun } from "../api/adapters";

// Test-env t stub: echoes the key plus interpolated values (i18n is not initialized
// in tests — assertions expect key strings; see no-hardcoded-cjk.test.ts rationale).
const t = (k: string, o?: Record<string, unknown>) =>
  [k, ...Object.values(o ?? {}).map(String)].join(" ").trim();
import type { RunDetailDto } from "../api/client.types";

const base: RunDetailDto = {
  run: {
    id: 7, conversation_id: "c1", spawn_id: 1, spawn_name: "Mermer",
    user_message: "查天气", total_ms: 1500, task_tokens: 42,
    status: "scored", overall_score: 8, overall_badge: "good",
    model: null, provider: null, tokens_in: null, tokens_out: null,
    tokens_estimated: false, error_kind: null, error_text: null,
    system_prompt: null, injected_kb: null, injected_kb_sources: null,
    final_output: null,
  },
  steps: [
    { seq: 0, kind: "route", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 80 },
    { seq: 1, kind: "dispatch", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 1200 },
    { seq: 2, kind: "tool_call", ref: { tool: "web_search", ok: true }, detail: {}, duration_ms: 300 },
  ],
  evaluations: [
    { dimension: "routing", status: "pass", score: 9, comment: "选对了人" },
    { dimension: "identity", status: "pass", score: 10, comment: "身份一致" },
  ],
};

describe("toUiRun", () => {
  it("translates step kinds to human labels", () => {
    const ui = toUiRun(base, t);
    expect(ui.steps[0].label).toContain("Mermer");      // route → replay.step_route + spawn
    expect(ui.steps[1].label).toContain("Mermer");      // dispatch → replay.step_dispatch + spawn
    expect(ui.steps[2].label).toBe("replay.tool_web_search"); // web_search → its label key
  });

  it("marks the slowest step", () => {
    const ui = toUiRun(base, t);
    expect(ui.steps.find((s) => s.isSlowest)?.kind).toBe("dispatch");
  });

  it("maps dimensions to human labels and exposes scored flag", () => {
    const ui = toUiRun(base, t);
    expect(ui.scored).toBe(true);
    const routing = ui.dimensions.find((d) => d.dimension === "routing");
    expect(routing?.label).toBe("replay.dim_routing");
  });

  it("scored=false while still recording", () => {
    const ui = toUiRun({ ...base, run: { ...base.run, status: "recorded", overall_score: null } }, t);
    expect(ui.scored).toBe(false);
  });

  it("exposes userMessage", () => {
    expect(toUiRun(base, t).userMessage).toBe("查天气");
  });
});

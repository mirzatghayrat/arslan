import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

describe("render_chart SVG artifact", () => {
  it("captures the svg artifact content onto the matching tool step", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 1 } as any);
    store().handleFrame({ type: "tool_call", tool: "render_chart", args_summary: "{}" } as any);
    store().handleFrame({
      type: "tool_result",
      tool: "render_chart",
      ok: true,
      summary: "rendered bar",
      artifact: { kind: "svg", content: "<svg>X</svg>" },
    } as any);

    const steps = store().activitySteps;
    expect(steps.length).toBe(1);
    expect(steps[0].artifactSvg).toBe("<svg>X</svg>");
    expect(JSON.stringify(store())).toContain("<svg>X</svg>");
  });

  it("captures the echarts spec onto the matching tool step", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 1 } as any);
    store().handleFrame({ type: "tool_call", tool: "render_chart", args_summary: "{}" } as any);
    store().handleFrame({
      type: "tool_result",
      tool: "render_chart",
      ok: true,
      summary: "rendered bar",
      artifact: { kind: "echarts", spec: { series: [{ type: "bar", data: [1, 2] }] } },
    } as any);

    const steps = store().activitySteps;
    expect(steps.length).toBe(1);
    expect(steps[0].artifactChart).toEqual({ series: [{ type: "bar", data: [1, 2] }] });
    expect(steps[0].artifactSvg).toBeUndefined();
  });

  it("leaves artifactSvg undefined when the tool_result has no artifact", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 1 } as any);
    store().handleFrame({ type: "tool_call", tool: "web_search", args_summary: "{}" } as any);
    store().handleFrame({
      type: "tool_result",
      tool: "web_search",
      ok: true,
      summary: "3 results",
    } as any);

    const steps = store().activitySteps;
    expect(steps[0].artifactSvg).toBeUndefined();
  });
});

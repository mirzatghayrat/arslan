import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunReplay from "../components/RunReplay";
import type { RunDetailDto } from "../api/client.types";

const scored: RunDetailDto = {
  run: { id: 7, conversation_id: "c1", spawn_id: 1, spawn_name: "Mermer",
    user_message: "查天气", total_ms: 1500, task_tokens: 42,
    status: "scored", overall_score: 8, overall_badge: "good",
    model: null, provider: null, tokens_in: null, tokens_out: null,
    tokens_estimated: false, error_kind: null, error_text: null,
    system_prompt: null, injected_kb: null },
  steps: [
    { seq: 0, kind: "route", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 80 },
    { seq: 1, kind: "dispatch", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 1200 },
  ],
  evaluations: [
    { dimension: "routing", status: "pass", score: 9, comment: "选对了人" },
    { dimension: "completion", status: "warn", score: 6, comment: "略简略" },
  ],
};

const scoredWithTool: RunDetailDto = {
  ...scored,
  steps: [
    ...scored.steps,
    {
      seq: 2,
      kind: "tool_call",
      ref: { tool: "web_search", ok: true },
      detail: { args_summary: '{"query":"OKX"}', summary: "5 results" },
      duration_ms: 300,
    },
  ],
};

const recording: RunDetailDto = {
  ...scored,
  run: { ...scored.run, status: "recorded", overall_score: null, overall_badge: null },
  evaluations: [],
};

const scoredWithP2: RunDetailDto = {
  ...scored,
  run: {
    ...scored.run,
    model: "gpt-x",
    provider: "openai",
    tokens_in: null,
    tokens_out: null,
    tokens_estimated: true,
    task_tokens: 1200,
    error_kind: "ToolError",
    error_text: "timeout hitting api",
    system_prompt: "SYS PROMPT TEXT",
    injected_kb: null,
  },
  steps: [
    ...scored.steps,
    {
      seq: 2,
      kind: "tool_call",
      ref: { tool: "web_search", ok: true },
      detail: {
        args_summary: '{"query":"OKX"}',
        summary: "5 results",
        args_full: '{"q":"x"}',
        result_raw: "RAW_MARKER_123",
      },
      duration_ms: 300,
    },
  ],
};

vi.mock("../api/client", () => ({
  api: { getRun: vi.fn(), getRunsSummary: vi.fn(), redactRun: vi.fn(), redactAllRuns: vi.fn() },
}));
// Real echarts needs a canvas/layout engine jsdom lacks — assert via a stub.
vi.mock("../components/EChart", () => ({
  default: () => <div data-testid="echart-stub" />,
}));
import { api } from "../api/client";

const SUMMARY = {
  scored_count: 3,
  avg_score: 7.67,
  pass_rate: 67,
  dimension_averages: { routing: 7.0, fabrication: null, identity: null, completion: 8.0 },
  per_spawn: [{ spawn_name: "Mermer", scored_count: 2, avg_score: 7.0, pass_rate: 50 }],
  recent: [
    { id: 1, overall_score: 8, created_at: null },
    { id: 2, overall_score: null, created_at: null },
    { id: 3, overall_score: 9, created_at: null },
  ],
};

describe("RunReplay", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.getRunsSummary as ReturnType<typeof vi.fn>).mockResolvedValue(SUMMARY);
  });

  it("renders KPI cards, steps, and dimensions when scored", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    render(<RunReplay runId={7} onClose={() => {}} />);

    await screen.findByText("交给 Mermer 处理");
    expect(screen.getByText("查天气")).toBeTruthy();
    expect(screen.getByText(/路由匹配/)).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
  });

  it("shows 评分中 while not scored, then refreshes", async () => {
    (api.getRun as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(recording)
      .mockResolvedValue(scored);
    render(<RunReplay runId={7} onClose={() => {}} pollMs={10} />);

    await screen.findByText(/评分中/);
    await waitFor(() => expect(screen.getByText(/路由匹配/)).toBeTruthy());
  });

  it("renders the 本次 vs 整体 compare chart when scored and scored_count >= 2", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByTestId("run-compare");
    expect(screen.getByText("本次 vs 整体")).toBeTruthy();
    expect(screen.getAllByTestId("echart-stub")).toHaveLength(1);
    // overall 8 vs fleet avg 7.67 → subtle delta line
    expect(screen.getByText(/平均 7\.7 · 本次 \+0\.3/)).toBeTruthy();
  });

  it("hides the compare chart when scored_count < 2", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    (api.getRunsSummary as ReturnType<typeof vi.fn>).mockResolvedValue({ ...SUMMARY, scored_count: 1 });
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText("编排回放");
    expect(screen.queryByTestId("run-compare")).toBeNull();
  });

  it("hides the compare chart when the summary fetch fails (best-effort)", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    (api.getRunsSummary as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText("编排回放");
    expect(screen.queryByTestId("run-compare")).toBeNull();
  });

  it("hides the compare chart while the run is unscored", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(recording);
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText(/评分中/);
    expect(screen.queryByTestId("run-compare")).toBeNull();
  });

  it("expands a tool step to reveal args_summary + result summary + ✓", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithTool);
    render(<RunReplay runId={7} onClose={() => {}} />);
    const label = await screen.findByText(/web_search|搜索|查资料|用工具/);
    fireEvent.click(label.closest("li")!);
    expect(screen.getByText(/OKX/)).toBeTruthy();
    expect(screen.getByText(/5 results/)).toBeTruthy();
    expect(screen.getByText("✓", { selector: ".trace__ok--yes" })).toBeTruthy();
  });

  it("does not show the detail until the row is clicked", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithTool);
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText(/web_search|搜索|查资料|用工具/);
    expect(screen.queryByText(/OKX/)).toBeNull();
  });

  it("shows the model and an estimated-token '约' mark", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithP2);
    render(<RunReplay runId={7} onClose={() => {}} />);
    expect(await screen.findByText(/gpt-x/)).toBeTruthy();
    expect(screen.getByText(/约/)).toBeTruthy();
  });

  it("shows a run-level error banner when error_text is present", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithP2);
    render(<RunReplay runId={7} onClose={() => {}} />);
    expect(await screen.findByText(/timeout hitting api/)).toBeTruthy();
  });

  it("expanding a tool step reveals full args + raw result", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithP2);
    render(<RunReplay runId={7} onClose={() => {}} />);
    const label = await screen.findByText(/web_search|搜索|查资料|用工具/);
    fireEvent.click(label.closest("li")!);
    expect(screen.getByText(/RAW_MARKER_123/)).toBeTruthy();
  });

  it("shows the system prompt / injected KB collapsible section", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithP2);
    render(<RunReplay runId={7} onClose={() => {}} />);
    expect(await screen.findByText(/SYS PROMPT TEXT/)).toBeTruthy();
  });

  it("shows a cleared-debug-detail placeholder when prompt/kb are both null", async () => {
    const redacted: RunDetailDto = {
      ...scored,
      run: { ...scored.run, system_prompt: null, injected_kb: null },
    };
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(redacted);
    render(<RunReplay runId={7} onClose={() => {}} />);
    expect(await screen.findByText(/调试详情已清除/)).toBeTruthy();
  });

  it("clear button calls redactRun after confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithP2);
    const spy = api.redactRun as ReturnType<typeof vi.fn>;
    spy.mockResolvedValue({ redacted: true });
    render(<RunReplay runId={7} onClose={() => {}} />);
    fireEvent.click(await screen.findByText(/清除.*调试详情|清除此/));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(7));
  });
});

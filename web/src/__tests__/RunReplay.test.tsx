import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunReplay, { isTerminalRunStatus } from "../components/RunReplay";
import type { RunDetailDto } from "../api/client.types";

const scored: RunDetailDto = {
  run: { id: 7, conversation_id: "c1", spawn_id: 1, spawn_name: "Mermer",
    user_message: "查天气", total_ms: 1500, task_tokens: 42,
    status: "scored", overall_score: 8, overall_badge: "good",
    model: null, provider: null, tokens_in: null, tokens_out: null,
    tokens_estimated: false, error_kind: null, error_text: null,
    system_prompt: null, injected_kb: null, injected_kb_sources: null },
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

const scoredWithBreakdown: RunDetailDto = {
  ...scored,
  steps: [
    { seq: 0, kind: "route", ref: {}, detail: {}, duration_ms: 20 },
    {
      seq: 1,
      kind: "tool_call",
      ref: { tool: "web_search", ok: true },
      detail: { args_summary: '{"query":"OKX"}', summary: "8 results" },
      duration_ms: 1200,
    },
    {
      seq: 2,
      kind: "dispatch",
      ref: {},
      detail: { output_preview: "半导体 2025 调研…" },
      duration_ms: 12700,
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
  api: { getRun: vi.fn(), getRunsSummary: vi.fn(), getRuns: vi.fn(), redactRun: vi.fn(), redactAllRuns: vi.fn() },
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
    (api.getRuns as ReturnType<typeof vi.fn>).mockResolvedValue([]);
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
    // one echart for the compare-bars, one for the dims radar (both render when scored)
    expect(screen.getAllByTestId("echart-stub")).toHaveLength(2);
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

  it("shows the model and an estimated-token '≈' mark", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithP2);
    render(<RunReplay runId={7} onClose={() => {}} />);
    expect(await screen.findByText(/gpt-x/)).toBeTruthy();
    expect(screen.getByText(/≈/)).toBeTruthy();
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

  it("shows a time-breakdown bar, tool cards with ✓, and the output preview", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scoredWithBreakdown);
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByTestId("time-breakdown");
    const card = screen.getByTestId("tool-card");
    expect(card).toBeTruthy();
    fireEvent.click(card);
    expect(screen.getByText(/OKX/)).toBeTruthy();
    expect(screen.getByText(/8 results/)).toBeTruthy();
    expect(screen.getByText(/半导体 2025/)).toBeTruthy();
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

  it("renders a dims radar, a spawn history sparkline, kb chips, and export buttons", async () => {
    const withKbAndSpawn: RunDetailDto = {
      ...scored,
      run: { ...scored.run, spawn_id: 2, injected_kb_sources: ["半导体行业笔记", "WSTS 数据源"] },
      evaluations: [
        { dimension: "routing", status: "pass", score: 9, comment: "选对了人" },
        { dimension: "fabrication", status: "pass", score: 8, comment: "无编造" },
        { dimension: "identity", status: "pass", score: 8, comment: "角色一致" },
        { dimension: "completion", status: "warn", score: 6, comment: "略简略" },
      ],
    };
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(withKbAndSpawn);
    (api.getRunsSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...SUMMARY,
      dimension_averages: { routing: 6, fabrication: 8.5, identity: 8.5, completion: 3.5 },
    });
    (api.getRuns as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 5, spawn_name: "Mermer", status: "scored", overall_score: 6, overall_badge: "ok", total_ms: 100, user_message: "x" },
      { id: 7, spawn_name: "Mermer", status: "scored", overall_score: 8.1, overall_badge: "good", total_ms: 100, user_message: "x" },
    ]);
    render(<RunReplay runId={7} onClose={() => {}} />);
    expect(await screen.findByTestId("dims-radar")).toBeTruthy();
    expect(screen.getByTestId("history-spark")).toBeTruthy();
    expect(screen.getByText(/半导体行业笔记/)).toBeTruthy();
    expect(screen.getByText(/导出 md/)).toBeTruthy();
    expect(screen.getByText(/导出 json/)).toBeTruthy();
  });

  it("renders a step waterfall with one bar per step, failed tool_call bar uses --danger", async () => {
    const withWaterfall: RunDetailDto = {
      ...scored,
      steps: [
        { seq: 0, kind: "route", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 100 },
        { seq: 1, kind: "tool_call", ref: { tool: "web_search", ok: false }, detail: {}, duration_ms: 0 },
        { seq: 2, kind: "dispatch", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 300 },
      ],
    };
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(withWaterfall);
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText("交给 Mermer 处理");

    const bars = screen.getAllByTestId("wf-bar");
    expect(bars).toHaveLength(3);
    // middle bar (seq 1, tool_call, ok:false) must render with the danger token
    const failedBar = bars[1] as HTMLElement;
    expect(failedBar.style.background).toContain("var(--danger)");
  });

  // S3-M1: cancelled/interrupted are terminal — the panel must not poll them forever.
  it("isTerminalRunStatus: terminal statuses stop polling, in-flight ones do not", () => {
    for (const s of ["scored", "score_failed", "cancelled", "interrupted", "replayed"]) {
      expect(isTerminalRunStatus(s)).toBe(true);
    }
    for (const s of ["recording", "recorded"]) {
      expect(isTerminalRunStatus(s)).toBe(false);
    }
  });

  for (const status of ["cancelled", "interrupted"] as const) {
    it(`schedules no further poll for a ${status} run`, async () => {
      const terminal: RunDetailDto = {
        ...scored,
        run: { ...scored.run, status, overall_score: null, overall_badge: null },
        evaluations: [],
      };
      (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(terminal);
      render(<RunReplay runId={7} onClose={() => {}} pollMs={10} />);
      await screen.findByText("编排回放");
      // Real timers, mirroring the polling test above: at pollMs=10 a leaked
      // timer would refetch several times within this window.
      await new Promise((r) => setTimeout(r, 60));
      expect(api.getRun).toHaveBeenCalledTimes(1);
    });
  }

  it("degrades gracefully: no spawnId → no sparkline, no kb sources → no chips, summary failure → no radar", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...scored,
      run: { ...scored.run, spawn_id: null, injected_kb_sources: null },
    });
    (api.getRunsSummary as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText("编排回放");
    expect(screen.queryByTestId("dims-radar")).toBeNull();
    expect(screen.queryByTestId("history-spark")).toBeNull();
    expect(api.getRuns).not.toHaveBeenCalled();
  });
});

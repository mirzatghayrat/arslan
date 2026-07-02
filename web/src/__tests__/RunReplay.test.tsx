import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunReplay from "../components/RunReplay";
import type { RunDetailDto } from "../api/client.types";

const scored: RunDetailDto = {
  run: { id: 7, conversation_id: "c1", spawn_id: 1, spawn_name: "Mermer",
    user_message: "查天气", total_ms: 1500, task_tokens: 42,
    status: "scored", overall_score: 8, overall_badge: "good" },
  steps: [
    { seq: 0, kind: "route", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 80 },
    { seq: 1, kind: "dispatch", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 1200 },
  ],
  evaluations: [
    { dimension: "routing", status: "pass", score: 9, comment: "选对了人" },
    { dimension: "completion", status: "warn", score: 6, comment: "略简略" },
  ],
};

const recording: RunDetailDto = {
  ...scored,
  run: { ...scored.run, status: "recorded", overall_score: null, overall_badge: null },
  evaluations: [],
};

vi.mock("../api/client", () => ({
  api: { getRun: vi.fn(), getRunsSummary: vi.fn() },
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

  it("renders the 3 fleet-wide charts at the bottom when scored_count >= 2", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByTestId("eval-charts");
    expect(screen.getAllByTestId("echart-stub")).toHaveLength(3);
    expect(screen.getByText("评分趋势")).toBeTruthy();
    expect(screen.getByText("四维平均")).toBeTruthy();
    expect(screen.getByText("分身达标率")).toBeTruthy();
  });

  it("hides the charts when scored_count < 2", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    (api.getRunsSummary as ReturnType<typeof vi.fn>).mockResolvedValue({ ...SUMMARY, scored_count: 1 });
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText("编排回放");
    expect(screen.queryByTestId("eval-charts")).toBeNull();
  });

  it("hides the charts when the summary fetch fails (best-effort)", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    (api.getRunsSummary as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("offline"));
    render(<RunReplay runId={7} onClose={() => {}} />);
    await screen.findByText("编排回放");
    expect(screen.queryByTestId("eval-charts")).toBeNull();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvalSummary from "../components/EvalSummary";

vi.mock("../api/client", () => ({ api: { getRuns: vi.fn(), getRun: vi.fn(), getRunsSummary: vi.fn() } }));
// Real echarts needs a canvas/layout engine jsdom lacks — assert via a stub.
vi.mock("../components/EChart", () => ({
  default: () => <div data-testid="echart-stub" />,
}));
import { api } from "../api/client";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const SUMMARY = {
  scored_count: 3,
  avg_score: 7.67,
  pass_rate: 67,
  dimension_averages: { routing: 7.0, fabrication: null, identity: null, completion: 8.0 },
  per_spawn: [
    { spawn_name: "Mermer", scored_count: 2, avg_score: 7.0, pass_rate: 50 },
    { spawn_name: "小美", scored_count: 1, avg_score: 9.0, pass_rate: 100 },
  ],
  recent: [
    { id: 1, overall_score: 8, created_at: null },
    { id: 2, overall_score: null, created_at: null },
    { id: 3, overall_score: 9, created_at: null },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.getRuns.mockResolvedValue([
    { id: 2, spawn_name: "小美", status: "scored", overall_score: 9, overall_badge: "good", total_ms: 1500, user_message: "写文案" },
    { id: 1, spawn_name: "Mermer", status: "recorded", overall_score: null, overall_badge: null, total_ms: 800, user_message: "查天气" },
  ]);
  m.getRunsSummary.mockResolvedValue(SUMMARY);
  m.getRun.mockResolvedValue({
    run: { id: 2, conversation_id: "c", spawn_id: 1, spawn_name: "小美", user_message: "写文案",
           total_ms: 1500, task_tokens: 10, status: "scored", overall_score: 9, overall_badge: "good" },
    steps: [], evaluations: [],
  });
});

describe("EvalSummary", () => {
  it("renders summary + rows", async () => {
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByText("小美");
    expect(screen.getByText("Mermer")).toBeTruthy();
    expect(screen.getByText(/评分中/)).toBeTruthy();
  });

  it("drills into RunReplay on row click", async () => {
    render(<EvalSummary onClose={() => {}} />);
    const row = await screen.findByText("小美");
    fireEvent.click(row);
    await screen.findByText("编排回放");
  });

  it("shows empty state", async () => {
    m.getRuns.mockResolvedValue([]);
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByText(/还没有运行记录/);
  });

  // Aggregate charts moved to the bottom of RunReplay (see RunReplay.test.tsx);
  // the summary list itself stays chart-free.
  it("renders no charts in the list view", async () => {
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByText("小美");
    expect(screen.queryByTestId("eval-charts")).toBeNull();
  });
});

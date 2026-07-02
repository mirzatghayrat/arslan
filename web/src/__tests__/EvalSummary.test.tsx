import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvalSummary from "../components/EvalSummary";

vi.mock("../api/client", () => ({ api: { getRuns: vi.fn(), getRun: vi.fn(), getRunsSummary: vi.fn() } }));
// Real echarts needs a canvas/layout engine jsdom lacks — assert via a stub.
vi.mock("../components/EChart", () => ({
  default: () => <div data-testid="echart-stub" />,
}));
// t() returns the key — scope-toggle assertions match on i18n keys.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
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

  // Aggregate charts live between the KPI row and the run list, but only in
  // the unfiltered global view (per-run comparison lives in RunReplay).
  it("renders the 3 fleet-wide charts in the global list view", async () => {
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByTestId("eval-charts");
    expect(screen.getAllByTestId("echart-stub")).toHaveLength(3);
    expect(screen.getByText("评分趋势")).toBeTruthy();
    expect(screen.getByText("四维平均")).toBeTruthy();
    expect(screen.getByText("分身达标率")).toBeTruthy();
  });

  it("renders no charts when filtered to a spawn", async () => {
    render(<EvalSummary onClose={() => {}} spawnId={1} />);
    await screen.findByText("小美");
    expect(screen.queryByTestId("eval-charts")).toBeNull();
  });

  it("renders no charts when scored_count < 2", async () => {
    m.getRunsSummary.mockResolvedValue({ ...SUMMARY, scored_count: 1 });
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByText("小美");
    expect(screen.queryByTestId("eval-charts")).toBeNull();
  });

  it("shows no scope toggle without a conversationId (unchanged global view)", async () => {
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByText("小美");
    expect(screen.queryByText("eval.scope_conversation")).toBeNull();
    expect(m.getRuns).toHaveBeenCalledWith(undefined, 50, undefined);
  });

  it("with conversationId defaults to a conversation-filtered fetch and hides charts", async () => {
    render(<EvalSummary onClose={() => {}} conversationId="conv-1" />);
    await screen.findByText("小美");
    expect(m.getRuns).toHaveBeenCalledWith(undefined, 50, "conv-1");
    expect(screen.queryByTestId("eval-charts")).toBeNull();
    // Toggle visible, defaulting to the conversation scope.
    const convTab = screen.getByText("eval.scope_conversation");
    expect(convTab.getAttribute("aria-selected")).toBe("true");
  });

  it("toggling to 全部会话 refetches unfiltered and shows the charts", async () => {
    render(<EvalSummary onClose={() => {}} conversationId="conv-1" />);
    await screen.findByText("小美");
    fireEvent.click(screen.getByText("eval.scope_all"));
    await screen.findByTestId("eval-charts");
    expect(m.getRuns).toHaveBeenLastCalledWith(undefined, 50, undefined);
    expect(screen.getByText("eval.scope_all").getAttribute("aria-selected")).toBe("true");
  });

  it("conversation scope + spawnId combine on the fetch", async () => {
    render(<EvalSummary onClose={() => {}} conversationId="conv-1" spawnId={3} />);
    await screen.findByText("小美");
    expect(m.getRuns).toHaveBeenCalledWith(3, 50, "conv-1");
  });
});

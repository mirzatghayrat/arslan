/**
 * 0.1.58 §7 Activity: lists in boxes that page inside, a run drawer that keeps the list's
 * place, state that survives leaving the page, a chart you can hover and click, icons.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: "en" } }),
}));
const { listRuns, getUsageSummary, request } = vi.hoisted(() => ({
  listRuns: vi.fn(), getUsageSummary: vi.fn(), request: vi.fn(),
}));
vi.mock("../api/client", () => ({ api: { listRuns, getUsageSummary }, request }));
vi.mock("../components/ScheduledTasksCard", () => ({ default: () => null }));
vi.mock("../components/RunReplay", () => ({ default: ({ runId }: { runId: number }) => <div data-testid="replay">run {runId}</div> }));

import ActivityView, { RUNS_PAGE } from "../components/ActivityView";
import UsageCard from "../components/UsageCard";
import JudgmentsCard from "../components/JudgmentsCard";
import HandsTraceCard from "../components/HandsTraceCard";
import { useActivityStore } from "../stores/activityStore";

const run = (id: number, origin = "chat") => ({ id, spawn_id: null, spawn_name: "Arslan", status: "recorded", overall_score: null,
  overall_badge: null, total_ms: 1200, user_message: `task ${id}`, created_at: "2026-10-09T08:00:00", origin });
const page = (from: number, n: number) => Array.from({ length: n }, (_, i) => run(from - i));
const BANDS = ["<10s", "10–30s", "30s–1m", "1–3m", "3–10m", ">10m"];
const summary = {
  range: "7d", daily: [], not_covered: [], tokens_total: 9000, usd_total: 0.1, estimated_any: false,
  rows: [{ provider: "deepseek", model: "deepseek-v4-flash", scope: "answer", tokens_total: 9000, usd: 0.1, estimated_any: false }],
  runs: { total: 3, done: 2, failed: 1, stopped: 0, running: 0, p50_ms: 4000, p95_ms: 9000 },
  bin_seconds: 3600, duration_bands: BANDS,
  bins: [
    { start_ts: 1_790_000_000, runs: 0, failed: 0, tokens_total: 0, durations: [0, 0, 0, 0, 0, 0] },
    { start_ts: 1_790_003_600, runs: 3, failed: 1, tokens_total: 9000, durations: [1, 1, 0, 0, 0, 0],
      p50_ms: 4000, max_ms: 9000, usd: 0.1, models: [{ model: "deepseek-v4-flash", tokens: 9000 }] },
  ],
};

beforeEach(() => {
  useActivityStore.setState({ range: "7d", filter: {}, openRunId: null, scroll: {} });
  getUsageSummary.mockResolvedValue(summary);
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("最近的工作", () => {
  it("shows where each run came from with its own icon", async () => {
    listRuns.mockResolvedValue([run(3, "job"), run(2, "phone"), run(1)]);
    render(<ActivityView />);
    await screen.findByTestId("activity-run-3");
    const origins = Array.from(document.querySelectorAll("[data-origin]")).map((el) => el.getAttribute("data-origin"));
    expect(origins).toEqual(["job", "phone", "chat"]);
  });

  it("opens a run in a drawer while the list stays, and Esc / arrows work", async () => {
    listRuns.mockResolvedValue([run(3), run(2), run(1)]);
    render(<ActivityView />);
    fireEvent.click(await screen.findByTestId("activity-run-2"));
    expect(screen.getByTestId("run-drawer")).toHaveTextContent("run 2");
    // the list is still there, with the opened row marked
    expect(screen.getByTestId("activity-run-2")).toHaveAttribute("aria-current", "true");
    expect(screen.getByTestId("activity-run-3")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(screen.getByTestId("run-drawer")).toHaveTextContent("run 1");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("run-drawer")).toBeNull();
  });

  it("loads the next 20 back from the last row when the box reaches its end", async () => {
    listRuns.mockResolvedValueOnce(page(100, RUNS_PAGE)).mockResolvedValueOnce(page(80, 5));
    render(<ActivityView />);
    const box = await screen.findByTestId("activity-runs-box");
    Object.defineProperty(box, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(box, "clientHeight", { value: 400, configurable: true });
    box.scrollTop = 600;
    fireEvent.scroll(box);
    await screen.findByTestId("activity-run-76");
    expect(listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ beforeId: 81, limit: RUNS_PAGE }));
  });

  it("comes back to the same place after leaving the page", async () => {
    listRuns.mockResolvedValue([run(3), run(2), run(1)]);
    const first = render(<ActivityView />);
    fireEvent.click(await screen.findByTestId("activity-run-2"));
    const box = screen.getByTestId("activity-runs-box");
    box.scrollTop = 120;
    fireEvent.scroll(box);
    first.unmount();                               // App unmounts the page on leaving it
    render(<ActivityView />);
    expect(await screen.findByTestId("run-drawer")).toHaveTextContent("run 2");
    expect((await screen.findByTestId("activity-runs-box")).scrollTop).toBe(120);
  });
});

describe("the usage chart", () => {
  it("hovering a column shows one card for that slice", async () => {
    render(<UsageCard />);
    fireEvent.mouseEnter(await screen.findByTestId("usage-col-1"));
    const card = screen.getByTestId("usage-hovercard");
    expect(card).toHaveTextContent('activityPage.sliceRuns:{"n":3,"failed":1}');
    expect(card).toHaveTextContent("activityPage.hoverTimes");
    expect(card).toHaveTextContent("deepseek-v4-flash");
  });

  it("clicking a column narrows recent work to that slice; the chip clears it", async () => {
    listRuns.mockResolvedValue([run(1)]);
    render(<ActivityView />);
    fireEvent.click(await screen.findByTestId("usage-col-1"));
    await waitFor(() => expect(listRuns).toHaveBeenLastCalledWith(
      expect.objectContaining({ since: 1_790_003_600, until: 1_790_007_200 })));
    expect(screen.getByTestId("activity-filter")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("activityPage.clearFilter"));
    await waitFor(() => expect(listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ since: undefined })));
  });

  it("clicking a model row narrows recent work to that model", async () => {
    listRuns.mockResolvedValue([run(1)]);
    render(<ActivityView />);
    fireEvent.click(await screen.findByTestId("usage-row"));
    await waitFor(() => expect(listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ model: "deepseek-v4-flash" })));
  });
});

describe("判断记录 and Hands", () => {
  it("gives each family of question its icon and pages back by id", async () => {
    const rows = Array.from({ length: 20 }, (_, i) => ({ id: 40 - i, point: i % 2 ? "memory.worth" : "tool.approval", mode: "active",
      verdict: true, probability: 0.8, latency_ms: 1, outcome: null, created_at: "2026-10-09T08:00:00Z" }));
    request.mockResolvedValueOnce({ items: rows }).mockResolvedValueOnce({ items: [] });
    render(<JudgmentsCard />);
    await screen.findByTestId("judgment-40");
    const icons = Array.from(document.querySelectorAll("[data-point-icon]")).slice(0, 2).map((el) => el.getAttribute("class") ?? "");
    expect(icons[0]).toContain("shield");
    expect(icons[1]).toContain("bookmark");
    const box = screen.getByTestId("judgments-box");
    Object.defineProperty(box, "scrollHeight", { value: 800, configurable: true });
    Object.defineProperty(box, "clientHeight", { value: 400, configurable: true });
    box.scrollTop = 400;
    fireEvent.scroll(box);
    await waitFor(() => expect(request).toHaveBeenLastCalledWith("/judgments?limit=20&before_id=21"));
  });

  it("shows Hands calls 20 at a time with an icon per kind of call", async () => {
    const entries = Array.from({ length: 30 }, (_, i) => ({ at: `2026-10-09T08:${String(i).padStart(2, "0")}:00Z`, app: "Notes",
      op: i === 0 ? "click" : "look", outcome: "ok" }));
    request.mockResolvedValue({ entries });
    render(<HandsTraceCard />);
    await screen.findAllByTestId("hands-row");
    expect(screen.getAllByTestId("hands-row")).toHaveLength(20);
    expect(document.querySelector('[data-op="click"]')?.getAttribute("class")).toContain("mouse-pointer-click");
    const box = screen.getByTestId("hands-box");
    Object.defineProperty(box, "scrollHeight", { value: 800, configurable: true });
    Object.defineProperty(box, "clientHeight", { value: 400, configurable: true });
    box.scrollTop = 400;
    act(() => { fireEvent.scroll(box); });
    expect(screen.getAllByTestId("hands-row")).toHaveLength(30);
  });
});

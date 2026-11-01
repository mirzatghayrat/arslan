/**
 * INB7-b (v0.1.64): Progress's one time axis, as board F draws it (the user's pick, 「2B」, relayed 2026-11-01). Over the last 24
 * hours the token row has a runs lane under it: each bar is one run, its length the time it took and its colour how it ended, amber
 * while it waits for your answer. Picking a bar puts that run's steps on a lane of their own, at the time each one started, and the
 * replay walks through them. Over 7 and 30 days the duration heatmap stays (the user: 「热力图只在 7 天和 30 天显示」), since a
 * week of bars would be too thin to read.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, request } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), request: vi.fn() }));
vi.mock("../api/client", () => ({ api: { getUsageSummary, listRuns, runProcess }, request }));

import UsageCard from "../components/UsageCard";
import { MAX_ROWS, MIN_BAR_MS, REPLAY_MS, packRows } from "../components/activity/RunsLane";
import type { WaitingView } from "../hooks/useWaiting";
import { useActivityStore } from "../stores/activityStore";

const T0 = 1_790_000_000;                          // the first hour on the axis (epoch seconds)
const HOUR = 3600;
const naive = (sec: number) => new Date(sec * 1000).toISOString().replace("Z", "");   // how /runs writes a time
const utc = (sec: number) => new Date(sec * 1000).toISOString().replace(".000", "");  // how /process writes one
const BANDS = ["<10s", "10–30s", "30s–1m", "1–3m", "3–10m", ">10m"];
const summary = (range: string) => ({
  range, daily: [], not_covered: [], rows: [], estimated_any: false, tokens_total: 0, usd_total: 0,
  runs: { total: 5, done: 2, failed: 1, stopped: 1, running: 2, p50_ms: 4000, p95_ms: 9000 },
  bin_seconds: HOUR, duration_bands: BANDS,
  bins: Array.from({ length: 24 }, (_, i) => ({ start_ts: T0 + i * HOUR, runs: i === 2 ? 2 : 0, failed: i === 2 ? 1 : 0,
    tokens_total: i === 2 ? 50_000 : 0, durations: [0, 0, 0, 0, 0, 0] })),
});
const run = (id: number, status: string, start: number, ms: number | null, over: Record<string, unknown> = {}) => ({
  id, spawn_id: null, spawn_name: "Arslan", status, overall_score: null, overall_badge: null, total_ms: ms,
  user_message: `Run ${id}`, created_at: naive(start), origin: "chat", model: "deepseek-v4-flash", tokens: 1000, ...over });
const RUNS = [
  run(11, "recorded", T0 + 2 * HOUR, 30 * 60_000),
  run(12, "failed", T0 + 2 * HOUR + 600, 10 * 60_000, { model: "claude-sonnet-5-5" }),
  run(13, "recording", T0 + 20 * HOUR, null, { waiting: true }),
  run(14, "recording", T0 + 22 * HOUR, null),
  run(15, "cancelled", T0 + 10 * HOUR, 60_000),
];
const PROCESS = {
  run_id: 11, status: "recorded", started_at: utc(T0 + 2 * HOUR), ended_at: utc(T0 + 2 * HOUR + 30 * 60),
  entries: [
    { kind: "note", text: "Looking first." },
    { kind: "tool", tool: "read_file", ok: true, ms: 40, args_summary: '{"path": "notes.md"}', summary: "12 lines", at: utc(T0 + 2 * HOUR + 5 * 60) },
    { kind: "tool", tool: "run_command", ok: false, ms: 900, args_summary: '{"command": "ls -la"}', summary: "exit 2", at: utc(T0 + 2 * HOUR + 20 * 60) },
    { kind: "tool", tool: "list_dir", ok: true, ms: 10, args_summary: "", summary: "3 entries", at: null },
  ],
};
const waiting = (): WaitingView => ({ count: 0, conversations: [], projects: [], scheduled: [], loaded: true });
const bar = (id: number) => screen.getByTestId(`axis-run-${id}`);

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, axisRunId: null, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue(RUNS);
  runProcess.mockResolvedValue(PROCESS);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe("runs share rows only when they do not overlap", () => {
  it("packs each run into the first row that is free when it starts, a short run counting as its shortest bar", () => {
    const min = (n: number) => n * 60_000;
    // 09:40 is short, but its bar is MIN_BAR_MS wide, so 09:50 cannot sit after it in the first row.
    const rows = packRows([
      { id: 1, start: min(0), end: min(30) }, { id: 2, start: min(10), end: min(20) },
      { id: 3, start: min(40), end: min(45) }, { id: 4, start: min(50), end: min(60) },
    ]);
    expect(MIN_BAR_MS).toBe(min(14));
    expect([1, 2, 3, 4].map((id) => rows.get(id))).toEqual([0, 1, 0, 1]);
  });

  it("stacks what does not fit into the last row rather than growing the lane without end", () => {
    const rows = packRows(Array.from({ length: MAX_ROWS + 3 }, (_, i) => ({ id: i, start: 0, end: 60_000 })));
    expect(Math.max(...rows.values())).toBe(MAX_ROWS - 1);
  });
});

describe("over 24 hours each run is a bar on the token row's axis", () => {
  it("places, sizes and colours each bar, and asks for the runs since the axis starts", async () => {
    render(<UsageCard waiting={waiting()} />);
    await waitFor(() => expect(bar(11)).toBeTruthy());
    expect(listRuns).toHaveBeenCalledWith({ since: T0, limit: 200 });
    // 02:00 of 24 hours is 8.33% in, and 30 minutes is 2.08% wide; one minute still draws the 14-minute bar.
    expect([bar(11).style.left, bar(11).style.width]).toEqual(["8.33%", "2.08%"]);
    expect(bar(15).style.width).toBe("0.97%");
    expect([11, 12].map((id) => bar(id).dataset.row)).toEqual(["0", "1"]);
    expect([11, 12, 13, 14, 15].map((id) => bar(id).dataset.outcome)).toEqual(["ok", "failed", "waiting", "running", "stopped"]);
    // A running bar reaches now and never runs off the axis.
    expect(parseFloat(bar(14).style.left) + parseFloat(bar(14).style.width)).toBeLessThanOrEqual(100);
    expect(bar(13).getAttribute("aria-label")).toContain("Waiting for you");
    // Board F has no heatmap over a day: the bars carry duration and outcome.
    expect(screen.queryByTestId("usage-heatmap")).toBeNull();
    expect(screen.queryByTestId("usage-outcomes")).toBeNull();
    const legend = screen.getByTestId("axis-legend");
    for (const word of ["Done", "Failed", "Waiting for you", "Running", "Stopped"]) expect(legend).toHaveTextContent(word);
    expect(screen.getByText("Each bar is one run: length is the time it took, colour is how it ended")).toBeTruthy();
  });

  it("keeps the duration heatmap over 7 and 30 days, with no bars", async () => {
    for (const range of ["7d", "30d"] as const) {
      useActivityStore.setState({ range });
      render(<UsageCard waiting={waiting()} />);
      await waitFor(() => expect(screen.getByTestId("usage-heatmap")).toBeTruthy());
      expect(screen.queryByTestId("axis-runs")).toBeNull();
      cleanup();
    }
    expect(listRuns).not.toHaveBeenCalled();
  });

  it("dims the runs a model filter leaves out of the list below", async () => {
    useActivityStore.setState({ filter: { model: "claude-sonnet-5-5" } });
    render(<UsageCard waiting={waiting()} />);
    await waitFor(() => expect(bar(12)).toBeTruthy());
    expect(bar(12).style.opacity).toBe("1");
    expect(bar(11).style.opacity).toBe("0.28");
  });
});

describe("a picked run's steps sit on the axis and replay in order", () => {
  it("picking a bar shows its steps at the time each started; picking it again lets it go", async () => {
    render(<UsageCard waiting={waiting()} />);
    await waitFor(() => expect(bar(11)).toBeTruthy());
    fireEvent.click(bar(11));
    expect(useActivityStore.getState().axisRunId).toBe(11);
    expect(bar(11).getAttribute("aria-pressed")).toBe("true");
    expect(bar(12).style.opacity).toBe("0.28");
    await waitFor(() => expect(screen.getByTestId("axis-steps")).toBeTruthy());
    expect(runProcess).toHaveBeenCalledWith(11);
    const ticks = within(screen.getByTestId("axis-steps")).getAllByTestId(/^axis-step-/);
    // 5 and 20 minutes into a 30-minute run; a step with no time keeps its place in the order.
    expect(ticks.map((tick) => tick.style.left)).toEqual(["16.67%", "66.67%", "83.33%"]);
    expect(ticks.map((tick) => tick.dataset.ok)).toEqual(["true", "false", "true"]);
    expect(screen.getByTestId("axis-position")).toHaveTextContent("3 / 3 steps");
    expect(screen.queryByText("Each bar is one run: length is the time it took, colour is how it ended")).toBeNull();
    fireEvent.click(bar(11));
    expect(useActivityStore.getState().axisRunId).toBeNull();
    expect(screen.queryByTestId("axis-steps")).toBeNull();
  });

  it("the replay shows one step at a time, stops at the last, and goes back to the start", async () => {
    useActivityStore.setState({ axisRunId: 11 });
    render(<UsageCard waiting={waiting()} />);
    await waitFor(() => expect(screen.getByTestId("axis-position")).toHaveTextContent("3 / 3 steps"));
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(screen.getByTestId("axis-position")).toHaveTextContent("1 / 3 steps");
    // The step in the words the conversation's step list uses (lib/process.stepWords).
    expect(screen.getByTestId("axis-caption")).toHaveTextContent("1. Read notes.md");
    const ticks = () => within(screen.getByTestId("axis-steps")).getAllByTestId(/^axis-step-/).map((tick) => tick.style.opacity);
    expect(ticks()).toEqual(["1", "0.25", "0.25"]);
    act(() => { vi.advanceTimersByTime(REPLAY_MS); });
    expect(screen.getByTestId("axis-position")).toHaveTextContent("2 / 3 steps");
    expect(screen.getByTestId("axis-caption")).toHaveTextContent("2. Ran ls -la");
    act(() => { vi.advanceTimersByTime(REPLAY_MS * 3); });
    expect(screen.getByTestId("axis-position")).toHaveTextContent("3 / 3 steps");
    expect(screen.getByRole("button", { name: "Replay" })).toBeTruthy();         // it stopped by itself at the last step
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));            // from the end, a replay starts over
    expect(screen.getByTestId("axis-position")).toHaveTextContent("1 / 3 steps");
    act(() => { vi.advanceTimersByTime(REPLAY_MS); });
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    act(() => { vi.advanceTimersByTime(REPLAY_MS * 2); });
    expect(screen.getByTestId("axis-position")).toHaveTextContent("2 / 3 steps");  // paused where it was
    fireEvent.click(screen.getByRole("button", { name: "Back to the start" }));
    expect(screen.getByTestId("axis-position")).toHaveTextContent("1 / 3 steps");
  });

  it("says so when the run only replied, and opens the run's details on request", async () => {
    runProcess.mockResolvedValue({ ...PROCESS, entries: [] });
    useActivityStore.setState({ axisRunId: 11 });
    render(<UsageCard waiting={waiting()} />);
    await waitFor(() => expect(screen.getByTestId("axis-position")).toHaveTextContent("Only a reply, no steps"));
    expect(screen.queryByRole("button", { name: "Replay" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(useActivityStore.getState().openRunId).toBe(11);
    fireEvent.click(screen.getByRole("button", { name: "Back to all runs" }));
    expect(useActivityStore.getState().axisRunId).toBeNull();
  });
});

describe("the axis speaks every language", () => {
  it("has its words in all six, and reads in Chinese as board F does", async () => {
    const keys = ["axisHint", "waitingRun", "chartSteps", "replay", "pause", "restart", "stepOf", "noSteps", "openRun", "allRuns"];
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of keys) {
        const value = i18n.getResource(language, "translation", `activityPage.${key}`);
        expect(typeof value === "string" && value.length > 0, `${language} ${key}`).toBe(true);
      }
    }
    await i18n.changeLanguage("zh");
    render(<UsageCard waiting={waiting()} />);
    await waitFor(() => expect(screen.getByText("每条是一次运行：长短 = 用时，颜色 = 结果")).toBeTruthy());
    expect(screen.getByTestId("axis-legend")).toHaveTextContent("等你");
  });
});

/**
 * INB7-c1 (v0.1.64): one pick on Progress, as board F draws it. A row of 「最近的工作」 and a bar on the axis pick the same run; the
 * inspector beside the list opens it, with its steps in the conversation's words, following the axis's replay and moving it when a
 * step is clicked. The drawer is one click away ("Details") until INB7-c4 folds what it shows into the inspector.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, getRun, request } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), getRun: vi.fn(), request: vi.fn() }));
vi.mock("../api/client", () => ({
  api: { getUsageSummary, listRuns, runProcess, getRun, getRunsSummary: () => new Promise(() => {}), getRuns: () => new Promise(() => {}) },
  request,
}));

import { PROACTIVE_CHANGED } from "../api/proactive";
import ActivityView from "../components/ActivityView";
import { REPLAY_MS } from "../components/activity/RunsLane";
import { useActivityStore } from "../stores/activityStore";

const T0 = 1_790_000_000;
const HOUR = 3600;
const naive = (sec: number) => new Date(sec * 1000).toISOString().replace("Z", "");
const utc = (sec: number) => new Date(sec * 1000).toISOString().replace(".000", "");
const summary = (range: string) => ({
  range, daily: [], not_covered: [], rows: [], estimated_any: false, tokens_total: 0, usd_total: 0,
  runs: { total: 3, done: 2, failed: 1, stopped: 0, running: 0, p50_ms: 4000, p95_ms: 9000 },
  bin_seconds: HOUR, duration_bands: ["<10s", "10–30s", "30s–1m", "1–3m", "3–10m", ">10m"],
  bins: Array.from({ length: 24 }, (_, i) => ({ start_ts: T0 + i * HOUR, runs: 0, failed: 0, tokens_total: 0, durations: [0, 0, 0, 0, 0, 0] })),
});
const run = (id: number, status: string, start: number, ms: number | null, over: Record<string, unknown> = {}) => ({
  id, spawn_id: null, spawn_name: "Arslan", status, overall_score: null, overall_badge: null, total_ms: ms,
  user_message: `Run ${id}`, created_at: naive(start), origin: "chat", model: "deepseek-v4-flash", tokens: 1000, ...over });
const RUNS = [run(12, "failed", T0 + 3 * HOUR, 10 * 60_000), run(11, "recorded", T0 + 2 * HOUR, 30 * 60_000),
  run(14, "recording", T0 + 22 * HOUR, null)];
const at = (min: number) => utc(T0 + 2 * HOUR + min * 60);
const PROCESS = {
  run_id: 11, status: "recorded", started_at: at(0), ended_at: at(30),
  entries: [
    { kind: "tool", tool: "read_file", ok: true, ms: 40, args_summary: '{"path": "notes.md"}', summary: "12 lines", at: at(5),
      detail: { view: "file", path: "notes.md", chars: 1200 } },
    { kind: "tool", tool: "run_command", ok: false, ms: 900, args_summary: '{"command": "ls -la"}', summary: "exit 2", at: at(20) },
    { kind: "tool", tool: "list_dir", ok: true, ms: 10, args_summary: '{"path": "Reports"}', summary: "3 entries", at: at(25) },
  ],
};
const TWELVE = { ...PROCESS, run_id: 12, status: "failed", entries: [
  { kind: "tool", tool: "read_file", ok: true, ms: 40, args_summary: '{"path": "other.md"}', summary: "3 lines", at: at(70),
    detail: { view: "file", path: "other.md", chars: 90 } }] };
const waiting = () => ({ count: 0, conversations: [], projects: [], scheduled: [], loaded: true });
const inspector = () => screen.getByTestId("run-inspector");
const steps = () => within(inspector()).getAllByTestId(/^inspector-step-/);

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue(RUNS);
  runProcess.mockImplementation((id: number) => Promise.resolve(id === 11 ? PROCESS : id === 12 ? TWELVE
    : { ...PROCESS, run_id: id, status: "recording", entries: [] }));
  getRun.mockReturnValue(new Promise(() => {}));
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe("one pick drives the list, the axis and the inspector", () => {
  it("a row picks the run: the inspector opens it, its bar is picked, and the drawer stays shut", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    expect(useActivityStore.getState().pickedRunId).toBe(11);
    expect(screen.getByTestId("activity-run-11").getAttribute("aria-current")).toBe("true");
    await waitFor(() => expect(screen.getByTestId("axis-run-11").getAttribute("aria-pressed")).toBe("true"));
    expect(within(inspector()).getByRole("heading")).toHaveTextContent("Run 11");
    expect(screen.queryByTestId("run-drawer")).toBeNull();
    // The axis's lane and the inspector open together and share one read of the steps.
    await waitFor(() => expect(steps()).toHaveLength(3));
    expect(runProcess).toHaveBeenCalledTimes(1);
  });

  it("a bar for a run the loaded list does not hold still opens with its name", async () => {
    listRuns.mockImplementation((o: { limit?: number }) => Promise.resolve(o.limit === 200
      ? [...RUNS, run(15, "recorded", T0 + 10 * HOUR, 60_000, { user_message: "Older than the page" })] : RUNS));
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("axis-run-15"));
    expect(within(inspector()).getByRole("heading")).toHaveTextContent("Older than the page");
  });

  it("picking another run starts its replay over", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(screen.getByTestId("axis-position")).toHaveTextContent("3 / 3 steps"));
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    fireEvent.click(screen.getByTestId("activity-run-12"));
    expect([useActivityStore.getState().replayStep, useActivityStore.getState().replayPlaying]).toEqual([null, false]);
  });

  it("a bar picks the same run in the list", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("axis-run-12"));
    expect(screen.getByTestId("activity-run-12").getAttribute("aria-current")).toBe("true");
    expect(within(inspector()).getByRole("heading")).toHaveTextContent("Run 12");
  });

  it("picking the picked row again lets it go, and the inspector says how to pick one", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    fireEvent.click(screen.getByTestId("activity-run-11"));
    expect(useActivityStore.getState().pickedRunId).toBeNull();
    expect(inspector()).toHaveTextContent("Pick a run on the axis or in the list to see what it did");
  });
});

describe("the inspector shows the picked run's steps and follows the replay", () => {
  it("lists the steps in the conversation's words with their times", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(steps()).toHaveLength(3));
    expect(steps().map((step) => step.textContent)).toEqual([
      expect.stringContaining("Read notes.md"), expect.stringContaining("Ran ls -la"), expect.stringContaining("Looked at Reports")]);
    expect(steps()[1].dataset.ok).toBe("false");
  });

  it("marks the step the replay shows, dims the ones ahead, and a click on a step moves the replay there", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(screen.getByTestId("axis-position")).toHaveTextContent("3 / 3 steps"));
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(steps()[0].getAttribute("aria-current")).toBe("step");
    expect(steps().map((step) => step.dataset.ahead)).toEqual(["false", "true", "true"]);
    fireEvent.click(within(steps()[1]).getByRole("button", { name: /Ran ls -la/ }));
    expect(screen.getByTestId("axis-position")).toHaveTextContent("2 / 3 steps");
    expect(useActivityStore.getState().replayPlaying).toBe(false);                // a click takes over from the player
    expect(steps()[1].getAttribute("aria-current")).toBe("step");
  });

  it("opens a step to its detail", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(steps()).toHaveLength(3));
    const toggle = within(steps()[0]).getByRole("button", { name: "Show details: Read notes.md" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(within(steps()[0]).getByText("notes.md")).toBeTruthy();
  });

  it("says why a running run has no steps yet", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-14"));
    await waitFor(() => expect(inspector()).toHaveTextContent("Still running: its steps show when it ends"));
  });

  it("over 7 days, with no axis, still lists the steps", async () => {
    useActivityStore.setState({ range: "7d" });
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(steps()).toHaveLength(3));
    expect(screen.queryByTestId("axis-steps")).toBeNull();
  });
});

describe("the inspector keeps up (⓪Plan's review of PR 624)", () => {
  it("lists a picked run's steps once it ends, over 7 days too, where no axis reads the runs again (A)", async () => {
    useActivityStore.setState({ range: "7d" });
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-14"));
    await waitFor(() => expect(inspector()).toHaveTextContent("Still running"));
    runProcess.mockImplementation((id: number) => Promise.resolve({ ...PROCESS, run_id: id }));       // it ended
    act(() => { window.dispatchEvent(new Event(PROACTIVE_CHANGED)); });
    await waitFor(() => expect(steps()).toHaveLength(3));
  });

  it("over a day the header follows the axis's fresh read: a run that ended says so", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-14"));
    await waitFor(() => expect(within(inspector()).getByRole("heading").nextElementSibling).toHaveTextContent("Running"));
    listRuns.mockResolvedValue(RUNS.map((r) => (r.id === 14 ? { ...r, status: "recorded", total_ms: 600_000 } : r)));
    act(() => { window.dispatchEvent(new Event(PROACTIVE_CHANGED)); });
    await waitFor(() => expect(within(inspector()).getByRole("heading").nextElementSibling).toHaveTextContent("Done"));
  });

  it("leaving the page stops a replay, so it is not still playing on return", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(screen.getByTestId("axis-position")).toHaveTextContent("3 / 3 steps"));
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(useActivityStore.getState().replayPlaying).toBe(true);
    cleanup();
    expect(useActivityStore.getState().replayPlaying).toBe(false);
  });

  it("a newly picked run opens with its own steps closed (F)", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(steps()).toHaveLength(3));
    fireEvent.click(within(steps()[0]).getByRole("button", { name: /Show details/ }));
    fireEvent.click(screen.getByTestId("activity-run-12"));
    await waitFor(() => expect(steps()).toHaveLength(1));
    expect(within(inspector()).queryByText("other.md")).toBeNull();
  });

  it("a replay that reaches its last step stops, and a new range starts it over (C)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(screen.getByTestId("axis-position")).toHaveTextContent("3 / 3 steps"));
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    await act(async () => { vi.advanceTimersByTime(REPLAY_MS * 4); });
    expect([useActivityStore.getState().replayStep, useActivityStore.getState().replayPlaying]).toEqual([2, false]);
    act(() => { useActivityStore.getState().setRange("7d"); });
    expect([useActivityStore.getState().replayStep, useActivityStore.getState().replayPlaying]).toEqual([null, false]);
  });
});

describe("the drawer is one click away", () => {
  it("a link from a reply opens the run in the drawer and picks it (B)", () => {
    act(() => { useActivityStore.getState().showRun(12); });
    expect([useActivityStore.getState().openRunId, useActivityStore.getState().pickedRunId]).toEqual([12, 12]);
  });

  it("the drawer's arrows move the pick with it (B)", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    fireEvent.click(within(inspector()).getByRole("button", { name: "Details" }));
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect([useActivityStore.getState().openRunId, useActivityStore.getState().pickedRunId]).toEqual([14, 14]);
    expect(screen.getByTestId("activity-run-14").getAttribute("aria-current")).toBe("true");
  });

  it("Details opens the drawer on the picked run; × lets the run go", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    fireEvent.click(within(inspector()).getByRole("button", { name: "Details" }));
    expect(useActivityStore.getState().openRunId).toBe(11);
    expect(screen.getByTestId("run-drawer")).toBeTruthy();
    fireEvent.click(within(inspector()).getByRole("button", { name: "Back to all runs" }));
    expect(useActivityStore.getState().pickedRunId).toBeNull();
  });
});

describe("the inspector speaks every language", () => {
  it("has its words in all six", () => {
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of ["inspectorHint", "details", "showDetail"]) {
        const value = i18n.getResource(language, "translation", `activityPage.${key}`);
        expect(typeof value === "string" && value.length > 0, `${language} ${key}`).toBe(true);
      }
    }
  });
});

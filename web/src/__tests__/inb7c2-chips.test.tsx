/**
 * INB7-c2 (v0.1.64): board F's chips over 「最近的工作」: 「要你做」, 「失败」, 「定时」, 「手机」, each with its count. The server filters
 * (GET /runs outcome= / origin=) and counts (GET /runs/counts), so a paged list and its counts agree. The list shows the page's
 * range, as the axis and the tiles do (board F: 「这个范围里没有」), and a chip also dims the bars it leaves out.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runCounts, runProcess, request } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runCounts: vi.fn(), runProcess: vi.fn(), request: vi.fn() }));
vi.mock("../api/client", () => ({ api: { getUsageSummary, listRuns, runCounts, runProcess }, request }));

import { PROACTIVE_CHANGED } from "../api/proactive";
import ActivityView from "../components/ActivityView";
import { useActivityStore } from "../stores/activityStore";

const HOUR = 3600;
const NOW = Math.floor(Date.now() / 1000);
const T0 = Math.floor(NOW / HOUR) * HOUR - 23 * HOUR;
const naive = (sec: number) => new Date(sec * 1000).toISOString().replace("Z", "");
const summary = (range: string) => ({
  range, daily: [], not_covered: [], rows: [], estimated_any: false, tokens_total: 0, usd_total: 0,
  runs: { total: 4, done: 2, failed: 1, stopped: 0, running: 1, p50_ms: 4000, p95_ms: 9000 },
  bin_seconds: HOUR, duration_bands: ["<10s", "10–30s", "30s–1m", "1–3m", "3–10m", ">10m"],
  bins: Array.from({ length: 24 }, (_, i) => ({ start_ts: T0 + i * HOUR, runs: 0, failed: 0, tokens_total: 0, durations: [0, 0, 0, 0, 0, 0] })),
});
const run = (id: number, status: string, origin: string, over: Record<string, unknown> = {}) => ({
  id, spawn_id: null, spawn_name: "Arslan", status, overall_score: null, overall_badge: null, total_ms: 60_000,
  user_message: `Run ${id}`, created_at: naive(T0 + id * HOUR), origin, model: "deepseek-v4-flash", tokens: 1000, ...over });
const RUNS = [run(5, "recording", "chat", { total_ms: null }), run(4, "recording", "chat", { waiting: true, total_ms: null }),
  run(3, "failed", "chat"), run(2, "recorded", "scheduled"), run(1, "recorded", "phone")];
const waiting = () => ({ count: 1, conversations: ["c"], projects: [], scheduled: [], loaded: true });
const chips = () => screen.getByTestId("activity-chips");
const chip = (name: RegExp) => within(chips()).getByRole("button", { name });
const listCalls = () => listRuns.mock.calls.map(([o]) => o).filter((o) => o.limit !== 200);   // the axis asks for 200

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue(RUNS);
  runCounts.mockResolvedValue({ waiting: 1, failed: 1, scheduled: 1, phone: 1 });
  runProcess.mockReturnValue(new Promise(() => {}));
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe("the list shows the page's range", () => {
  it("asks for the range's runs, and for a picked slice only", async () => {
    render(<ActivityView waiting={waiting()} />);
    await screen.findByTestId("activity-run-3");
    expect(listCalls()[0].since).toBeGreaterThanOrEqual(NOW - 24 * HOUR - 5);
    expect(listCalls()[0].since).toBeLessThanOrEqual(NOW - 24 * HOUR + 60);
    useActivityStore.setState({ filter: { since: T0 + 2 * HOUR, until: T0 + 3 * HOUR } });
    await waitFor(() => expect(listCalls().at(-1)).toMatchObject({ since: T0 + 2 * HOUR, until: T0 + 3 * HOUR }));
  });

  it("over 7 days asks for the week", async () => {
    useActivityStore.setState({ range: "7d" });
    render(<ActivityView waiting={waiting()} />);
    await screen.findByTestId("activity-run-3");
    expect(Math.abs(listCalls()[0].since - (NOW - 7 * 24 * HOUR))).toBeLessThan(60);
  });

  it("says when nothing ran in the range", async () => {
    listRuns.mockResolvedValue([]);
    render(<ActivityView waiting={waiting()} />);
    expect(await screen.findByTestId("activity-empty")).toHaveTextContent("Nothing ran in this range.");
  });
});

describe("each chip lists its runs, counted by the server in the same range", () => {
  it("shows the four chips with their counts, read for the list's range and model", async () => {
    runCounts.mockResolvedValue({ waiting: 2, failed: 5, scheduled: 0, phone: 7 });
    useActivityStore.setState({ filter: { model: "deepseek-v4-flash" } });
    render(<ActivityView waiting={waiting()} />);
    await waitFor(() => expect(chip(/Failed/)).toHaveTextContent("5"));
    expect([chip(/Needs you/), chip(/Scheduled/), chip(/iPhone/)].map((b) => b.textContent)).toEqual(["Needs you2", "Scheduled0", "iPhone7"]);
    const [scope] = runCounts.mock.calls[0];
    expect(scope.model).toBe("deepseek-v4-flash");
    expect(Math.abs(scope.since - (NOW - 24 * HOUR))).toBeLessThan(60);
  });

  it("asks the server for the chip's runs, and a second click clears it", async () => {
    render(<ActivityView waiting={waiting()} />);
    await screen.findByTestId("activity-run-3");
    const cases = [[/Needs you/, { outcome: "waiting" }], [/Failed/, { outcome: "failed" }], [/Scheduled/, { origin: "scheduled" }],
      [/iPhone/, { origin: "phone" }]] as const;
    for (const [name, params] of cases) {
      fireEvent.click(chip(name));
      expect(chip(name).getAttribute("aria-pressed")).toBe("true");
      await waitFor(() => expect(listCalls().at(-1)).toMatchObject(params));
    }
    const before = listCalls().length;
    fireEvent.click(chip(/iPhone/));
    expect(chip(/iPhone/).getAttribute("aria-pressed")).toBe("false");
    await waitFor(() => expect(listCalls().length).toBe(before + 1));
    expect([listCalls().at(-1).outcome, listCalls().at(-1).origin]).toEqual([undefined, undefined]);
  });

  it("pages back with the chip still on", async () => {
    listRuns.mockImplementation((o: { limit?: number; beforeId?: number }) => Promise.resolve(o.limit === 200 ? RUNS
      : o.beforeId ? [] : Array.from({ length: 20 }, (_, i) => run(100 - i, "failed", "chat"))));
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await within(await screen.findByTestId("activity-chips")).findByRole("button", { name: /Failed/ }));
    const box = await screen.findByTestId("activity-runs-box");
    Object.defineProperty(box, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(box, "clientHeight", { value: 200, configurable: true });
    box.scrollTop = 800;
    fireEvent.scroll(box);
    await waitFor(() => expect(listCalls().at(-1)).toMatchObject({ beforeId: 81, outcome: "failed" }));
  });

  it("dims the bars on the axis that the chip leaves out", async () => {
    render(<ActivityView waiting={waiting()} />);
    await screen.findByTestId("axis-run-1");
    fireEvent.click(chip(/iPhone/));
    expect([1, 2, 3, 4, 5].map((id) => screen.getByTestId(`axis-run-${id}`).style.opacity)).toEqual(["1", "0.28", "0.28", "0.28", "0.28"]);
    fireEvent.click(chip(/Needs you/));                                            // running is not waiting on you
    expect([1, 2, 3, 4, 5].map((id) => screen.getByTestId(`axis-run-${id}`).style.opacity)).toEqual(["0.28", "0.28", "0.28", "1", "0.28"]);
  });
});

describe("the review of PR 627", () => {
  it("names each chip with its count, and says what 「要你做」 lists here (5, 2)", async () => {
    runCounts.mockResolvedValue({ waiting: 2, failed: 5, scheduled: 0, phone: 7 });
    render(<ActivityView waiting={waiting()} />);
    await waitFor(() => expect(within(chips()).getByRole("button", { name: "Failed, 5" })).toBeTruthy());
    expect(within(chips()).getByRole("button", { name: "Needs you, 2" }).getAttribute("title"))
      .toBe("Runs waiting for your answer in their conversation");
  });

  it("reads the counts with a fresh start each time, and page 1 again when they change (4)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<ActivityView waiting={waiting()} />);
    await screen.findByTestId("activity-run-3");
    await waitFor(() => expect(runCounts).toHaveBeenCalled());
    const firstSince = runCounts.mock.calls[0][0].since;
    const lists = listCalls().length;
    vi.setSystemTime(Date.now() + HOUR * 1000);
    runCounts.mockResolvedValue({ waiting: 1, failed: 2, scheduled: 1, phone: 1 });                // a run failed meanwhile
    act(() => { window.dispatchEvent(new Event(PROACTIVE_CHANGED)); });
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(lists));
    expect(runCounts.mock.calls.at(-1)![0].since - firstSince).toBeGreaterThanOrEqual(HOUR - 5);
  });

  it("leaves the list alone when the counts change after the reader paged further back", async () => {
    listRuns.mockImplementation((o: { limit?: number; beforeId?: number }) => Promise.resolve(o.limit === 200 ? RUNS
      : o.beforeId ? [run(50, "recorded", "chat")] : Array.from({ length: 20 }, (_, i) => run(100 - i, "recorded", "chat"))));
    render(<ActivityView waiting={waiting()} />);
    const box = await screen.findByTestId("activity-runs-box");
    await waitFor(() => expect(runCounts).toHaveBeenCalled());
    Object.defineProperty(box, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(box, "clientHeight", { value: 200, configurable: true });
    box.scrollTop = 800;
    fireEvent.scroll(box);
    await screen.findByTestId("activity-run-50");                                  // page 2 is in
    const lists = listCalls().length;
    runCounts.mockResolvedValue({ waiting: 0, failed: 9, scheduled: 1, phone: 1 });
    act(() => { window.dispatchEvent(new Event(PROACTIVE_CHANGED)); });
    await waitFor(() => expect(runCounts.mock.calls.length).toBeGreaterThan(1));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(listCalls().length).toBe(lists);
    expect(screen.getByTestId("activity-run-50")).toBeTruthy();
  });

  it("clearing the slice keeps the chip on (7)", async () => {
    useActivityStore.setState({ filter: { since: T0 + 2 * HOUR, until: T0 + 3 * HOUR, chip: "failed" } });
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByLabelText("Clear filter"));
    expect(useActivityStore.getState().filter.chip).toBe("failed");
    await waitFor(() => expect(listCalls().at(-1)).toMatchObject({ outcome: "failed", until: undefined }));
  });
});

describe("the chips speak every language", () => {
  it("has their words in all six, and reads in Chinese as board F does", async () => {
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of ["chipScheduled", "chipPhone", "noneInRange", "chipNeedsTitle"]) {
        const value = i18n.getResource(language, "translation", `activityPage.${key}`);
        expect(typeof value === "string" && value.length > 0, `${language} ${key}`).toBe(true);
      }
    }
    await i18n.changeLanguage("zh");
    render(<ActivityView waiting={waiting()} />);
    await waitFor(() => expect(chips()).toHaveTextContent("要你做"));
    for (const word of ["失败", "定时", "手机"]) expect(chips()).toHaveTextContent(word);
  });
});

/**
 * INB7-c4a (v0.1.64): board F's 「诊断」 tab in the inspector. It shows the picked run's facts (run, model, tokens in and out, cost,
 * duration, score), its problems (the run's own error and its failed steps), and the drawer's two tools that matter here: clearing
 * the run's debug details and exporting it as Markdown. The drawer stays behind "Details" until the user decides on its radar and
 * sparkline (⓪Plan, 2026-11-01).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, runCounts, runChanges, getRun, getRunAnomalies, redactRun, request, confirmSheet, triggerDownload } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), runCounts: vi.fn(), runChanges: vi.fn(), getRun: vi.fn(), getRunAnomalies: vi.fn(),
  redactRun: vi.fn(), request: vi.fn(), confirmSheet: vi.fn(), triggerDownload: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: { getUsageSummary, listRuns, runProcess, runCounts, runChanges, getRun, getRunAnomalies, redactRun }, request,
}));
vi.mock("../components/kit", async (importOriginal) => ({ ...(await importOriginal<typeof import("../components/kit")>()), confirmSheet }));
vi.mock("../components/MessageBody", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../components/MessageBody")>()), triggerDownload }));

import ActivityView from "../components/ActivityView";
import { useActivityStore } from "../stores/activityStore";

const T0 = 1_790_000_000;
const HOUR = 3600;
const naive = (sec: number) => new Date(sec * 1000).toISOString().replace("Z", "");
const summary = (range: string) => ({
  range, daily: [], not_covered: [], rows: [], estimated_any: false, tokens_total: 0, usd_total: 0,
  runs: { total: 2, done: 2, failed: 0, stopped: 0, running: 0, p50_ms: 1, p95_ms: 1 },
  bin_seconds: HOUR, duration_bands: ["<10s"],
  bins: Array.from({ length: 24 }, (_, i) => ({ start_ts: T0 + i * HOUR, runs: 0, failed: 0, tokens_total: 0, durations: [0] })),
});
const run = (id: number, status = "recorded") => ({
  id, spawn_id: null, spawn_name: "Arslan", status, overall_score: null, overall_badge: null, total_ms: 95_000,
  user_message: `Run ${id}`, created_at: naive(T0 + id * HOUR), origin: "chat", model: "deepseek-v4-flash", tokens: 1 });
const RUNS = [run(12), run(11)];
const PROCESS = { run_id: 11, status: "scored", conversation_id: "chat-a", usage: { usd: 0.0083 }, entries: [
  { kind: "tool", tool: "read_file", ok: true, ms: 10, args_summary: '{"path": "notes.md"}', summary: "ok", at: null },
  { kind: "tool", tool: "run_command", ok: false, ms: 900, args_summary: '{"command": "make test"}', summary: "exit 2", at: null }] };
const detail = (over: Record<string, unknown> = {}, evaluations: unknown[] = []) => ({ artifacts: [], steps: [], evaluations, run: {
  id: 11, conversation_id: "chat-a", spawn_id: null, spawn_name: "Arslan", user_message: "Run 11", total_ms: 95_000, task_tokens: 21_000,
  status: "scored", overall_score: 8.4, overall_badge: "good", model: "deepseek-v4-flash", provider: "deepseek", tokens_in: 19_000,
  tokens_out: 2_000, tokens_estimated: false, error_kind: null, error_text: null, system_prompt: "s", injected_kb: null, ...over } });
const waiting = () => ({ count: 0, conversations: [], projects: [], scheduled: [], loaded: true });
const inspector = () => screen.getByTestId("run-inspector");
const panel = () => within(inspector()).getByRole("tabpanel");
const openDiag = async (id = 11) => {
  if (useActivityStore.getState().pickedRunId === id) useActivityStore.setState({ pickedRunId: null, pickedRun: null });
  fireEvent.click(await screen.findByTestId(`activity-run-${id}`));
  fireEvent.click(await within(inspector()).findByRole("tab", { name: /Diagnosis/ }));
};

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue(RUNS);
  runCounts.mockReturnValue(new Promise(() => {}));
  runChanges.mockReturnValue(new Promise(() => {}));
  runProcess.mockResolvedValue(PROCESS);
  getRun.mockResolvedValue(detail());
  getRunAnomalies.mockResolvedValue([]);
  redactRun.mockResolvedValue({ ok: true });
  confirmSheet.mockResolvedValue(true);
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the 「诊断」 tab", () => {
  it("shows the run's facts: run, model, tokens in and out, cost, duration and score", async () => {
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    await waitFor(() => expect(panel()).toHaveTextContent("#11"));
    expect(getRun).toHaveBeenCalledWith(11);
    const facts = within(panel()).getByTestId("diag-facts");
    for (const text of ["deepseek-v4-flash", "deepseek", "19k", "2k", "$0.0083", "1m 35s", "8.4/10", "good"]) {
      expect(facts).toHaveTextContent(text);
    }
  });

  it("says when the tokens are an estimate and when the run was not scored", async () => {
    getRun.mockResolvedValue(detail({ tokens_estimated: true, tokens_in: null, tokens_out: null, status: "recorded", overall_score: null,
      overall_badge: null }));
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    await waitFor(() => expect(within(panel()).getByTestId("diag-facts")).toHaveTextContent("≈ 21k"));
    expect(within(panel()).getByTestId("diag-facts")).toHaveTextContent("Not scored");
  });

  it("lists the problems: the run's own error and each failed step, and counts them on the tab", async () => {
    getRun.mockResolvedValue(detail({ status: "failed", error_kind: "timeout", error_text: "the model took too long" }));
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    const problems = await within(panel()).findAllByTestId("diag-problem");
    expect(problems.map((p) => p.textContent)).toEqual([expect.stringContaining("the model took too long"),
      expect.stringContaining("Ran make test")]);
    expect(within(inspector()).getByRole("tab", { name: /Diagnosis/ })).toHaveTextContent("2");
  });

  it("says when nothing went wrong", async () => {
    runProcess.mockResolvedValue({ ...PROCESS, entries: [PROCESS.entries[0]] });
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    await waitFor(() => expect(panel()).toHaveTextContent("Nothing went wrong"));
  });

  it("clears the run's debug details after asking, and reads the run again", async () => {
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    fireEvent.click(await within(panel()).findByRole("button", { name: "Clear this run's debug details" }));
    await waitFor(() => expect(redactRun).toHaveBeenCalledWith(11));
    expect(confirmSheet).toHaveBeenCalled();
    await waitFor(() => expect(getRun).toHaveBeenCalledTimes(2));
  });

  it("does not clear when the question is declined", async () => {
    confirmSheet.mockResolvedValue(false);
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    fireEvent.click(await within(panel()).findByRole("button", { name: "Clear this run's debug details" }));
    await waitFor(() => expect(confirmSheet).toHaveBeenCalled());
    expect(redactRun).not.toHaveBeenCalled();
  });

  it("exports the run as Markdown, as the drawer does", async () => {
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    fireEvent.click(await within(panel()).findByRole("button", { name: "Export md" }));
    expect(triggerDownload).toHaveBeenCalledWith("run-11.md", expect.stringContaining("Run 11"), "text/markdown;charset=utf-8");
  });

  it("keeps the drawer one click away until the user decides on its charts", async () => {
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    expect(within(inspector()).getByRole("button", { name: "Details" })).toBeTruthy();
  });
});

describe("the review of PR 631", () => {
  it("lists what the judge failed, so a run scored low for fabrication is not 'Nothing went wrong' (1)", async () => {
    runProcess.mockResolvedValue({ ...PROCESS, entries: [PROCESS.entries[0]] });
    getRun.mockResolvedValue(detail({ overall_score: 2.1, overall_badge: "bad" }, [
      { dimension: "fabrication", status: "fail", score: 2.1, comment: "cited a page that does not exist" },
      { dimension: "completeness", status: "warn", score: 6, comment: "left one step out" },
      { dimension: "relevance", status: "pass", score: 9, comment: "on topic" }]));
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    const problems = await within(panel()).findAllByTestId("diag-problem");
    expect(problems.map((p) => p.textContent)).toEqual([expect.stringContaining("cited a page that does not exist")]);
    expect(panel()).not.toHaveTextContent("Nothing went wrong");
    expect(within(panel()).getByTestId("diag-facts")).toHaveTextContent("⚠ 1");          // a warning shows on the score row
  });

  it("says when the judge could not score the run, and lists this run's failing streak", async () => {
    runProcess.mockResolvedValue({ ...PROCESS, entries: [PROCESS.entries[0]] });
    getRun.mockResolvedValue(detail({ status: "score_failed", overall_score: null, overall_badge: null }));
    getRunAnomalies.mockResolvedValue([
      { severity: "red", kind: "fabrication", spawn_id: 1, spawn_name: "Arslan", title_key: "anomaly.dim_streak.title",
        detail_key: "anomaly.dim_streak.detail", params: { dim: "fabrication", streak: 3 }, since: null, run_id: 11 },
      { severity: "red", kind: "fabrication", spawn_id: 1, spawn_name: "Arslan", title_key: "anomaly.dim_streak.title",
        detail_key: "anomaly.dim_streak.detail", params: { dim: "fabrication", streak: 2 }, since: null, run_id: 99 }]);
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    const problems = await within(panel()).findAllByTestId("diag-problem");
    expect(problems.map((p) => p.textContent)).toEqual([expect.stringContaining("The judge couldn't score this run"),
      expect.stringContaining("3+ runs in a row failed")]);
  });

  it("reads the steps again after a clear, so the cleared details are gone from the replay too (2)", async () => {
    runProcess.mockResolvedValue({ ...PROCESS, entries: [{ ...PROCESS.entries[0], raw: { args: "SECRET ARGS", result: "r" },
      detail: { view: "file", path: "notes.md" } }] });
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    const reads = runProcess.mock.calls.length;
    runProcess.mockResolvedValue({ ...PROCESS, entries: [{ ...PROCESS.entries[0], detail: { view: "file", path: "notes.md" } }] });
    fireEvent.click(await within(panel()).findByRole("button", { name: "Clear this run's debug details" }));
    await waitFor(() => expect(runProcess.mock.calls.length).toBeGreaterThan(reads));
    fireEvent.click(within(inspector()).getByRole("tab", { name: /Replay/ }));
    fireEvent.click(await within(inspector()).findByRole("button", { name: /Show details/ }));
    expect(inspector()).not.toHaveTextContent("SECRET ARGS");
  });

  it("can't be cleared twice while its question is open", async () => {
    confirmSheet.mockReturnValue(new Promise(() => {}));
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    const clear = await within(panel()).findByRole("button", { name: "Clear this run's debug details" });
    fireEvent.click(clear);
    await waitFor(() => expect(within(panel()).getByRole("button", { name: /Clear|Clearing/ })).toBeDisabled());
  });

  it("reads the run's record only once 「诊断」 is opened", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await within(inspector()).findByRole("tab", { name: /Diagnosis/ });
    expect(getRun).not.toHaveBeenCalled();
    expect(getRunAnomalies).not.toHaveBeenCalled();
    fireEvent.click(within(inspector()).getByRole("tab", { name: /Diagnosis/ }));
    await waitFor(() => expect(getRun).toHaveBeenCalledWith(11));
  });

  it("reads the record again once the picked run ends (W5), and marks estimated tokens even with in and out (W9)", async () => {
    listRuns.mockResolvedValue([run(12), run(11, "recording")]);
    runProcess.mockResolvedValue({ ...PROCESS, status: "recording", entries: [] });
    getRun.mockResolvedValue(detail({ tokens_estimated: true, status: "recording" }));
    useActivityStore.setState({ range: "7d" });
    render(<ActivityView waiting={waiting()} />);
    await openDiag();
    await waitFor(() => expect(within(panel()).getByTestId("diag-facts")).toHaveTextContent("≈ 21k"));
    const reads = getRun.mock.calls.length;
    runProcess.mockResolvedValue(PROCESS);
    listRuns.mockResolvedValue(RUNS);
    window.dispatchEvent(new Event("arslan:proactive-changed"));
    await waitFor(() => expect(getRun.mock.calls.length).toBeGreaterThan(reads));
  });
});

describe("the tab speaks every language", () => {
  it("has its words in all six", () => {
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of ["diagTab", "diagRun", "diagModel", "diagTokens", "diagCost", "diagDuration", "diagScore", "notScored",
        "problems", "noProblems", "judgeFailed"]) {
        const value = i18n.getResource(language, "translation", `activityPage.${key}`);
        expect(typeof value === "string" && value.length > 0, `${language} ${key}`).toBe(true);
      }
    }
  });
});

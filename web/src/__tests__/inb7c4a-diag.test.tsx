/**
 * INB7-c4a (v0.1.64): board F's 「诊断」 tab in the inspector. It shows the picked run's facts (run, model, tokens in and out, cost,
 * duration, score), its problems (the run's own error and its failed steps), and the drawer's two tools that matter here: clearing
 * the run's debug details and exporting it as Markdown. The drawer stays behind "Details" until the user decides on its radar and
 * sparkline (⓪Plan, 2026-11-01).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, runCounts, runChanges, getRun, redactRun, request, confirmSheet, triggerDownload } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), runCounts: vi.fn(), runChanges: vi.fn(), getRun: vi.fn(),
  redactRun: vi.fn(), request: vi.fn(), confirmSheet: vi.fn(), triggerDownload: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: { getUsageSummary, listRuns, runProcess, runCounts, runChanges, getRun, redactRun }, request,
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
const detail = (over: Record<string, unknown> = {}) => ({ artifacts: [], steps: [], evaluations: [], run: {
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

describe("the tab speaks every language", () => {
  it("has its words in all six", () => {
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of ["diagTab", "diagRun", "diagModel", "diagTokens", "diagCost", "diagDuration", "diagScore", "notScored",
        "problems", "noProblems"]) {
        const value = i18n.getResource(language, "translation", `activityPage.${key}`);
        expect(typeof value === "string" && value.length > 0, `${language} ${key}`).toBe(true);
      }
    }
  });
});

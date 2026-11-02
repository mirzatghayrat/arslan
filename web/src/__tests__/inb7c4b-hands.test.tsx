/**
 * INB7-c4b (v0.1.64): the picked run's Hands calls and judgments in 「诊断」. A Hands call belongs to a run by its `run_id` (#632),
 * never by time, since a late entry has the right id but a later time; an older entry with no id falls back to the run's
 * conversation and time window, marked "matched by time". Judgments go the same way since #637 gave each its `run_id`: by id,
 * and a row with none (one judged before migration 0085) by conversation and window, marked "matched by time".
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, request } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), request: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: { getUsageSummary, listRuns, runProcess, runCounts: () => new Promise(() => {}), runChanges: () => new Promise(() => {}),
    getRun: () => Promise.resolve({ artifacts: [], steps: [], evaluations: [], run: { id: 11, conversation_id: "chat-a", spawn_id: null,
      spawn_name: "Arslan", user_message: "Run 11", total_ms: 600_000, task_tokens: 1, status: "recorded", overall_score: null,
      overall_badge: null, model: "m", provider: "p", tokens_in: 1, tokens_out: 1, tokens_estimated: false, error_kind: null,
      error_text: null, system_prompt: "s", injected_kb: null } }), getRunAnomalies: () => Promise.resolve([]) }, request,
}));

import ActivityView from "../components/ActivityView";
import { useActivityStore } from "../stores/activityStore";

const T0 = 1_790_000_000;
const HOUR = 3600;
const iso = (sec: number) => new Date(sec * 1000).toISOString();
const naive = (sec: number) => iso(sec).replace("Z", "");
const START = T0 + 11 * HOUR;                     // run 11 runs from START for 10 minutes, in conversation chat-a
const END = START + 600;
const summary = (range: string) => ({
  range, daily: [], not_covered: [], rows: [], estimated_any: false, tokens_total: 0, usd_total: 0,
  runs: { total: 1, done: 1, failed: 0, stopped: 0, running: 0, p50_ms: 1, p95_ms: 1 },
  bin_seconds: HOUR, duration_bands: ["<10s"],
  bins: Array.from({ length: 24 }, (_, i) => ({ start_ts: T0 + i * HOUR, runs: 0, failed: 0, tokens_total: 0, durations: [0] })),
});
const run = (id: number) => ({
  id, spawn_id: null, spawn_name: "Arslan", status: "recorded", overall_score: null, overall_badge: null, total_ms: 600_000,
  user_message: `Run ${id}`, created_at: naive(T0 + id * HOUR), origin: "chat", model: "m", tokens: 1 });
const PROCESS = { run_id: 11, status: "scored", conversation_id: "chat-a", started_at: iso(START), ended_at: iso(END), entries: [] };
const hand = (target: string, over: Record<string, unknown>) => ({ at: iso(START + 60), app: "Notes", op: "click", outcome: "ok",
  target, conversation: "chat-a", job: null, run_id: null, ...over });
const TRACE = [
  hand("own id, late", { run_id: 11, at: iso(END + 300) }),       // its id says run 11 though it is logged after the run ended
  hand("other run's id, inside", { run_id: 12 }),                  // inside run 11's window, but its id says run 12
  hand("no id, inside", {}),
  hand("no id, other conversation", { conversation: "chat-b" }),
  hand("no id, after", { at: iso(END + 600) }),
];
const judged = (id: number, over: Record<string, unknown>) => ({ id, point: "memory.worth", mode: "active", verdict: true,
  probability: 0.9, latency_ms: 10, outcome: null, conversation_id: "chat-a", run_id: null, created_at: iso(START + 120), state: {},
  ...over });
const JUDGMENTS = [
  judged(5, { run_id: 11, created_at: iso(END + 3 * HOUR) }),   // its id says run 11, though judged long after (project evidence)
  judged(6, { run_id: 12 }),                                    // inside run 11's window and conversation, but its id says run 12
  judged(1, {}),
  judged(2, { point: "job.accomplished", created_at: iso(END + 60) }),       // right after the reply: the after-turn judgments
  judged(3, { conversation_id: "chat-b" }),
  judged(4, { created_at: iso(END + 3600) }),
];
const inspector = () => screen.getByTestId("run-inspector");
const panel = () => within(inspector()).getByRole("tabpanel");
const openDiag = async () => {
  fireEvent.click(await screen.findByTestId("activity-run-11"));
  fireEvent.click(await within(inspector()).findByRole("tab", { name: /Diagnosis/ }));
};
const reads = (path: string) => request.mock.calls.filter(([p]) => String(p).startsWith(path)).length;

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue([run(11)]);
  runProcess.mockResolvedValue(PROCESS);
  request.mockImplementation((path: string) => Promise.resolve(
    path.startsWith("/hands/trace") ? { entries: TRACE } : path.startsWith("/judgments") ? { items: JUDGMENTS } : { items: [], entries: [] }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the run's Hands calls in 「诊断」", () => {
  it("are the calls with its id, a late one included, never another run's by time; an older one with no id falls back to its window", async () => {
    render(<ActivityView waiting={{ count: 0, conversations: [], projects: [], scheduled: [], loaded: true }} />);
    await openDiag();
    const rows = await within(panel()).findAllByTestId("diag-hands-row");
    expect(rows.map((r) => r.getAttribute("data-target"))).toEqual(["own id, late", "no id, inside"]);
    expect(rows[0]).not.toHaveTextContent("by time");
    expect(rows[1]).toHaveTextContent("by time");
  });
});

describe("the run's judgments in 「诊断」", () => {
  it("are the ones with its id, a late one included, never another run's by time; one with no id falls back to its window", async () => {
    render(<ActivityView waiting={{ count: 0, conversations: [], projects: [], scheduled: [], loaded: true }} />);
    await openDiag();
    const rows = await within(panel()).findAllByTestId("diag-judgment");
    expect(rows.map((r) => r.getAttribute("data-id"))).toEqual(["5", "1", "2"]);
    expect(rows[0]).not.toHaveTextContent("by time");
    for (const row of rows.slice(1)) {
      expect(row).toHaveTextContent("by time");
      expect(within(row).getByText("by time").getAttribute("title")).toContain("can also show under a run next to this one");
    }
    expect(rows[1]).toHaveTextContent("Worth remembering");
  });
});

describe("what each section looked through when it found nothing (#634 review)", () => {
  it("says so in both, once read, and says nothing before", async () => {
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => { answer = resolve; });
    request.mockImplementation((path: string) => path.startsWith("/hands/trace")
      ? held.then(() => ({ entries: [] }))                             // the inspector's read waits
      : Promise.resolve(path.startsWith("/judgments") ? { items: [] } : { items: [], entries: [] }));
    render(<ActivityView waiting={{ count: 0, conversations: [], projects: [], scheduled: [], loaded: true }} />);
    await openDiag();
    await within(panel()).findByTestId("diag-facts");
    expect(within(panel()).queryByTestId("diag-hands")).toBeNull();
    expect(within(panel()).queryByTestId("diag-judgments")).toBeNull();
    answer();
    expect(await within(panel()).findByText(/No Mac app actions found in the last 7 days \(newest 500\)/)).toBeTruthy();
    expect(within(panel()).getByText(/No judgments found among the newest 500/)).toBeTruthy();
  });
});

describe("a running run (#634 review, Y5 and Y7)", () => {
  it("has a window to now, and its calls and judgments are read again once it stops", async () => {
    listRuns.mockResolvedValue([{ ...run(11), status: "recording", total_ms: null }]);
    runProcess.mockResolvedValue({ ...PROCESS, status: "recording", ended_at: null });
    render(<ActivityView waiting={{ count: 0, conversations: [], projects: [], scheduled: [], loaded: true }} />);
    await openDiag();
    const rows = await within(panel()).findAllByTestId("diag-hands-row");
    // Y7: while it runs, a call with no id after where it would end is still inside its window (to now).
    expect(rows.map((r) => r.getAttribute("data-target"))).toContain("no id, after");
    const trace = reads("/hands/trace");
    // Y5: it stops; the next read of its steps says so, and the trace and the ledger are read again.
    runProcess.mockResolvedValue(PROCESS);
    listRuns.mockResolvedValue([run(11)]);
    window.dispatchEvent(new Event("arslan:proactive-changed"));
    await waitFor(() => expect(reads("/hands/trace")).toBeGreaterThan(trace));
    await waitFor(() => expect(within(panel()).getAllByTestId("diag-hands-row").map((r) => r.getAttribute("data-target")))
      .not.toContain("no id, after"));
  });
});

describe("they are read only once 「诊断」 opens", () => {
  it("does not read the trace or the ledger for a pick alone", async () => {
    render(<ActivityView waiting={{ count: 0, conversations: [], projects: [], scheduled: [], loaded: true }} />);
    await screen.findByTestId("activity-run-11");
    const trace = reads("/hands/trace"), ledger = reads("/judgments");   // none since INB7-c4c dropped the page's cards
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await within(inspector()).findByRole("tab", { name: /Diagnosis/ });
    expect(reads("/hands/trace")).toBe(trace);
    expect(reads("/judgments")).toBe(ledger);
    fireEvent.click(within(inspector()).getByRole("tab", { name: /Diagnosis/ }));
    await waitFor(() => expect(reads("/hands/trace")).toBe(trace + 1));
    expect(reads("/judgments")).toBe(ledger + 1);
  });
});

describe("the words", () => {
  it("are in all six", async () => {
    for (const lng of SUPPORTED_LANGUAGES) {
      await i18n.changeLanguage(lng);
      for (const key of ["matchedByTime", "matchedByTimeNote", "noHandsFound", "noJudgmentsFound"]) {
        expect(i18n.exists(`activityPage.${key}`), `${lng}: ${key}`).toBe(true);
      }
    }
  });
});

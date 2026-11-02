/**
 * INB7-c4c (v0.1.64): board F folds Hands and the judgments into the inspector; the page's two full records stay at its foot, each
 * its own collapsed row (the user, 2026-11-02). What the cards guarded is also in 「诊断」 (an icon per kind of call and per family of question,
 * typed text as a length only, the judge's view and what you chose, a shadow question marked). The 「应用」 chip lists the runs that
 * used Mac apps, counted and paged by the server.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, runCounts, request } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), runCounts: vi.fn(), request: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: { getUsageSummary, listRuns, runProcess, runCounts, runChanges: () => new Promise(() => {}),
    getRun: () => Promise.resolve({ artifacts: [], steps: [], evaluations: [], run: { id: 11, conversation_id: "chat-a", spawn_id: null,
      spawn_name: "Arslan", user_message: "Run 11", total_ms: 600_000, task_tokens: 1, status: "recorded", overall_score: null,
      overall_badge: null, model: "m", provider: "p", tokens_in: 1, tokens_out: 1, tokens_estimated: false, error_kind: null,
      error_text: null, system_prompt: "s", injected_kb: null } }),
    getRunAnomalies: () => Promise.resolve([]) }, request,
}));

import ActivityView from "../components/ActivityView";
import { useActivityStore } from "../stores/activityStore";

const T0 = 1_790_000_000;
const HOUR = 3600;
const iso = (sec: number) => new Date(sec * 1000).toISOString();
const START = T0 + 11 * HOUR;
const summary = (range: string) => ({
  range, daily: [], not_covered: [], rows: [], estimated_any: false, tokens_total: 0, usd_total: 0,
  runs: { total: 1, done: 1, failed: 0, stopped: 0, running: 0, p50_ms: 1, p95_ms: 1 },
  bin_seconds: HOUR, duration_bands: ["<10s"],
  bins: Array.from({ length: 24 }, (_, i) => ({ start_ts: T0 + i * HOUR, runs: 0, failed: 0, tokens_total: 0, durations: [0] })),
});
const run = { id: 11, spawn_id: null, spawn_name: "Arslan", status: "recorded", overall_score: null, overall_badge: null,
  total_ms: 600_000, user_message: "Run 11", created_at: iso(START).replace("Z", ""), origin: "chat", model: "m", tokens: 1 };
const PROCESS = { run_id: 11, status: "scored", conversation_id: "chat-a", started_at: iso(START), ended_at: iso(START + 600), entries: [] };
const TRACE = [
  { at: iso(START + 60), app: "Notes", op: "set_value", outcome: "ok", target: "Body", typed_chars: 9, conversation: "chat-a", run_id: 11 },
  { at: iso(START + 90), app: "Notes", op: "click", outcome: "ok", target: "Save", conversation: "chat-a", run_id: 11 },
];
const JUDGMENTS = [
  { id: 1, point: "project.progress", mode: "shadow", verdict: false, probability: 0.2, latency_ms: 400, outcome: "declined",
    conversation_id: "chat-a", created_at: iso(START + 120) },
  { id: 2, point: "memory.worth", mode: "active", verdict: null, probability: null, latency_ms: 2000, outcome: null,
    conversation_id: "chat-a", created_at: iso(START + 130) },
];
const waiting = { count: 0, conversations: [], projects: [], scheduled: [], loaded: true };
const inspector = () => screen.getByTestId("run-inspector");
const panel = () => within(inspector()).getByRole("tabpanel");

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue([run]);
  runCounts.mockResolvedValue({ waiting: 0, failed: 0, scheduled: 0, phone: 0, apps: 4 });
  runProcess.mockResolvedValue(PROCESS);
  request.mockImplementation((path: string) => Promise.resolve(
    path.startsWith("/hands/trace") ? { entries: TRACE } : path.startsWith("/judgments") ? { items: JUDGMENTS } : { items: [], entries: [] }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the 「应用」 chip", () => {
  it("asks the server for the runs that used Mac apps, with its count", async () => {
    render(<ActivityView waiting={waiting} />);
    const chip = await screen.findByRole("button", { name: "Apps, 4" });
    fireEvent.click(chip);
    await waitFor(() => expect(listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ used: "apps" })));
    expect(chip).toHaveAttribute("aria-pressed", "true");
  });
});

describe("the two records at the page's foot (the user, 2026-11-02: kept on Progress, each its own collapsed row)", () => {
  const read = () => request.mock.calls.map(([p]) => String(p)).filter((p) => p.startsWith("/hands/trace") || p.startsWith("/judgments"));

  it("are two titled rows, both collapsed, and read nothing until opened", async () => {
    render(<ActivityView waiting={waiting} />);
    await screen.findByTestId("activity-run-11");
    const hands = screen.getByTestId("activity-hands-records"), judged = screen.getByTestId("activity-judgment-records");
    expect(hands).toHaveTextContent("Mac app actions (last 7 days)");
    expect(judged).toHaveTextContent("Judgment log");
    expect([hands.getAttribute("aria-expanded"), judged.getAttribute("aria-expanded")]).toEqual(["false", "false"]);
    expect(screen.queryByTestId("hands-trace")).toBeNull();
    expect(screen.queryByTestId("judgments-card")).toBeNull();
    expect(read()).toEqual([]);
  });

  it("each opens on its own and reads only its own list", async () => {
    render(<ActivityView waiting={waiting} />);
    await screen.findByTestId("activity-run-11");
    fireEvent.click(screen.getByTestId("activity-hands-records"));
    expect(await screen.findByTestId("hands-trace")).toBeTruthy();
    expect(screen.queryByTestId("judgments-card")).toBeNull();
    expect(read()).toEqual(["/hands/trace?days=7&limit=100"]);
    expect(within(screen.getByTestId("hands-trace")).queryByRole("heading")).toBeNull();   // the row's title is the one title
    fireEvent.click(screen.getByTestId("activity-judgment-records"));
    expect(await screen.findByTestId("judgments-card")).toBeTruthy();
    expect(read()).toEqual(["/hands/trace?days=7&limit=100", "/judgments?limit=20"]);
    expect(within(screen.getByTestId("judgments-card")).queryByRole("heading")).toBeNull();
    fireEvent.click(screen.getByTestId("activity-hands-records"));                     // folds again; the other stays open
    expect(screen.queryByTestId("hands-trace")).toBeNull();
    expect(screen.getByTestId("judgments-card")).toBeTruthy();
  });

  it("an opened row with nothing recorded says so", async () => {
    request.mockImplementation((path: string) => Promise.resolve(
      path.startsWith("/hands/trace") ? { entries: [] } : path.startsWith("/judgments") ? { items: [] } : { items: [], entries: [] }));
    render(<ActivityView waiting={waiting} />);
    await screen.findByTestId("activity-run-11");
    fireEvent.click(screen.getByTestId("activity-hands-records"));
    fireEvent.click(screen.getByTestId("activity-judgment-records"));
    expect(await screen.findAllByText("Nothing recorded yet.")).toHaveLength(2);
  });
});

describe("what the cards guarded, in 「诊断」", () => {
  it("an icon per kind of call, typed text as a length only; the judge's view, what you chose, and a shadow question marked", async () => {
    render(<ActivityView waiting={waiting} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    fireEvent.click(await within(inspector()).findByRole("tab", { name: /Diagnosis/ }));
    const calls = await within(panel()).findAllByTestId("diag-hands-row");
    expect(calls[0]).toHaveTextContent(/Body\W? \(9\)/);                       // the target is isolated (outside text)
    expect(calls[1].querySelector("[data-op]")?.getAttribute("class")).toContain("mouse-pointer-click");
    const judged = within(panel()).getAllByTestId("diag-judgment");
    expect(judged[0]).toHaveTextContent("Said project work is done?");
    expect(judged[0]).toHaveTextContent("shadow");
    expect(judged[0]).toHaveTextContent("no 80%");
    expect(judged[0]).toHaveTextContent("you declined");
    expect(judged[0].querySelector("[data-point-icon]")?.getAttribute("class")).toContain("flag");
    expect(judged[1]).toHaveTextContent("no answer");
    expect(judged[1]).not.toHaveTextContent("shadow");
    expect(judged[1].querySelector("[data-point-icon]")?.getAttribute("class")).toContain("bookmark");
  });
});

describe("the chip's word", () => {
  it("is in all six", async () => {
    for (const lng of SUPPORTED_LANGUAGES) {
      await i18n.changeLanguage(lng);
      expect(i18n.exists("activityPage.chipApps"), lng).toBe(true);
      for (const key of ["handsRecords", "judgmentRecords", "noRecords"]) expect(i18n.exists(`activityPage.${key}`), `${lng} ${key}`).toBe(true);
    }
  });
});

/**
 * INB7-c3 (v0.1.64): board F's 「改动」 tab in the inspector. It reads what the picked run changed from that run's own
 * checkpoint (GET /runs/{id}/changes, ⓪Plan's review of PR 629) and says which state it is in: running, finishing, kept,
 * none, expired or not saved. A kept text path opens the DIFF1 side-by-side reader in place, as it does from the Overview; an
 * undone turn lists its paths without opening them. The tabs follow the WAI-ARIA tabs pattern.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, runCounts, runChanges, request, changeDiff } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), runCounts: vi.fn(), runChanges: vi.fn(), request: vi.fn(),
  changeDiff: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: { getUsageSummary, listRuns, runProcess, runCounts, runChanges, getRun: () => new Promise(() => {}), getRunAnomalies: () => new Promise(() => {}) }, request,
}));
vi.mock("../api/files", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api/files")>();
  return { ...real, filesApi: { ...real.filesApi, changeDiff } };
});

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
  id, spawn_id: null, spawn_name: "Arslan", status, overall_score: null, overall_badge: null, total_ms: status === "recording" ? null : 60_000,
  user_message: `Run ${id}`, created_at: naive(T0 + id * HOUR), origin: "chat", model: "m", tokens: 1 });
const RUNS = [run(12), run(11)];
const process = (id: number) => ({ run_id: id, status: "recorded", conversation_id: "chat-a", entries: [
  { kind: "tool", tool: "write_file", ok: true, ms: 10, args_summary: '{"path": "notes.md"}', summary: "ok", at: null }] });
const KEPT = { state: "kept", undone: false, conversation_id: "chat-a", paths: [
  { folder: "/Users/a/Notes", path: "notes.md", kind: "edited" }, { folder: "/Users/a/Notes", path: "drafts/plan.md", kind: "made" },
  { folder: "/Users/a/Notes", path: "old.png", kind: "deleted" }] };
const DIFF = { reason: null, kind: "edited", added: 1, removed: 1, since: false,
  lines: [[" ", 1, 1, "# Notes"], ["-", 2, null, "old line"], ["+", null, 2, "new line"]] };
const waiting = () => ({ count: 0, conversations: [], projects: [], scheduled: [], loaded: true });
const inspector = () => screen.getByTestId("run-inspector");
const tab = (name: RegExp) => within(inspector()).getByRole("tab", { name });
const openChanges = async (id = 11) => {
  if (useActivityStore.getState().pickedRunId === id) useActivityStore.setState({ pickedRunId: null, pickedRun: null });  // a re-render
  const reads = runChanges.mock.calls.length;
  fireEvent.click(await screen.findByTestId(`activity-run-${id}`));
  await waitFor(() => expect(runChanges.mock.calls.length).toBeGreaterThan(reads));
  expect(runChanges).toHaveBeenLastCalledWith(id);
  fireEvent.click(await within(inspector()).findByRole("tab", { name: /Changes/ }));
};

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue(RUNS);
  runCounts.mockReturnValue(new Promise(() => {}));
  runProcess.mockImplementation((id: number) => Promise.resolve(process(id)));
  runChanges.mockImplementation((id: number) => Promise.resolve(id === 11 ? KEPT : { ...KEPT, state: "none", paths: [] }));
  changeDiff.mockResolvedValue(DIFF);
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe("the 「改动」 tab", () => {
  it("lists the picked run's own paths, from its own checkpoint", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(tab(/Changes/)).toHaveTextContent("3"));
    expect(tab(/Replay/).getAttribute("aria-selected")).toBe("true");          // the replay is the first tab, as on board F
    fireEvent.click(tab(/Changes/));
    expect(runChanges).toHaveBeenCalledWith(11);
    const rows = within(inspector()).getAllByTestId("inspector-change");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("notes.md"), expect.stringContaining("plan.md"), expect.stringContaining("old.png")]);
    expect(rows[0]).toHaveTextContent("Edited");
    expect(rows[1]).toHaveTextContent("Made");
  });

  it("opens a text path in the DIFF1 reader with the run's conversation, and back to the list", async () => {
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    fireEvent.click(within(within(inspector()).getAllByTestId("inspector-change")[0]).getByRole("button"));
    await waitFor(() => expect(changeDiff).toHaveBeenCalledWith("chat-a", 11, "/Users/a/Notes", "notes.md"));
    expect(await within(inspector()).findByText("new line")).toBeTruthy();
    fireEvent.click(within(inspector()).getByTestId("diff-back"));                  // the reader's own Back
    const rows = within(inspector()).getAllByTestId("inspector-change");
    expect(within(rows[2]).queryByRole("button")).toBeNull();                        // an image has no line diff
  });

  it("lists an undone turn's paths without opening them", async () => {
    runChanges.mockResolvedValue({ ...KEPT, undone: true });
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    expect(within(inspector()).getByText("Undone")).toBeTruthy();
    expect(within(inspector()).getAllByTestId("inspector-change").every((row) => within(row).queryByRole("button") === null)).toBe(true);
  });

  it("says which state the run's changes are in (⓪Plan's review of PR 629)", async () => {
    const cases = [["running", "Its changes show when it ends"], ["finishing", "Saving how it left the files"],
      ["none", "No files changed"], ["expired", "No record kept: changes are kept 7 days"],
      ["not_saved", "Its folder couldn't be saved, so its changes weren't kept"],
      ["interrupted", "Interrupted: how it left the files wasn't recorded"]] as const;
    for (const [state, words] of cases) {
      runChanges.mockResolvedValue({ state, undone: false, paths: [], conversation_id: "chat-a" });
      render(<ActivityView waiting={waiting()} />);
      await openChanges();
      await waitFor(() => expect(within(inspector()).getByRole("tabpanel")).toHaveTextContent(words));
      cleanup();
    }
  });

  it("says when it is still reading, and when the read failed", async () => {
    runChanges.mockReturnValue(new Promise(() => {}));
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    expect(within(inspector()).getByRole("tabpanel")).toHaveTextContent("Loading its changes");
    cleanup();
    runChanges.mockRejectedValue(new Error("offline"));
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    await waitFor(() => expect(within(inspector()).getByRole("tabpanel")).toHaveTextContent("Couldn't load its changes"));
  });

  it("while finishing, reads again on the beat until the state changes, and gives up after a few beats", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    runChanges.mockResolvedValue({ state: "finishing", undone: false, paths: [], conversation_id: "chat-a" });
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    await waitFor(() => expect(within(inspector()).getByRole("tabpanel")).toHaveTextContent("Saving"));
    runChanges.mockResolvedValue(KEPT);
    await act(async () => { vi.advanceTimersByTime(30_000); });
    await waitFor(() => expect(within(inspector()).getAllByTestId("inspector-change")).toHaveLength(3));
    cleanup();
    runChanges.mockClear();
    runChanges.mockResolvedValue({ state: "finishing", undone: false, paths: [], conversation_id: "chat-a" });
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    for (let beat = 0; beat < 6; beat += 1) await act(async () => { vi.advanceTimersByTime(30_000); });
    const reads = runChanges.mock.calls.length;
    expect(reads).toBeLessThanOrEqual(6);                                           // a few reads, not one per beat for ever
    for (let beat = 0; beat < 6; beat += 1) await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(runChanges.mock.calls.length).toBe(reads);                               // it gave up
    expect(within(inspector()).getByRole("tabpanel")).toHaveTextContent("Not recorded yet");   // and no longer says "Saving…"
  });

  it("reads the changes again once the picked run ends", async () => {
    listRuns.mockResolvedValue([run(12), run(11, "recording")]);
    runProcess.mockImplementation((id: number) => Promise.resolve({ ...process(id), status: "recording", entries: [] }));
    runChanges.mockResolvedValue({ state: "running", undone: false, paths: [], conversation_id: "chat-a" });
    useActivityStore.setState({ range: "7d" });
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    await waitFor(() => expect(within(inspector()).getByRole("tabpanel")).toHaveTextContent("Its changes show when it ends"));
    runProcess.mockImplementation((id: number) => Promise.resolve({ ...process(id), status: "recorded" }));
    runChanges.mockResolvedValue(KEPT);
    listRuns.mockResolvedValue(RUNS);
    act(() => { window.dispatchEvent(new Event("arslan:proactive-changed")); });
    await waitFor(() => expect(tab(/Changes/)).toHaveTextContent("3"));
  });

  it("a newly picked run opens on the replay again", async () => {
    render(<ActivityView waiting={waiting()} />);
    await openChanges();
    fireEvent.click(screen.getByTestId("activity-run-12"));
    await waitFor(() => expect(tab(/Replay/).getAttribute("aria-selected")).toBe("true"));
  });
});

describe("the tabs follow the WAI-ARIA tabs pattern (⓪Plan's review of PR 629, 3)", () => {
  it("ties each tab to its panel, keeps one tab in the tab order, and moves with the arrows, Home and End", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    const [replay, changes, diag] = within(inspector()).getAllByRole("tab");      // 「回放」, 「改动」, 「诊断」 (INB7-c4a)
    const panel = within(inspector()).getByRole("tabpanel");
    expect(replay.getAttribute("aria-controls")).toBe(panel.id);
    expect(panel.getAttribute("aria-labelledby")).toBe(replay.id);
    expect([replay.tabIndex, changes.tabIndex, diag.tabIndex]).toEqual([0, -1, -1]);
    fireEvent.keyDown(replay, { key: "ArrowRight" });
    expect(changes.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(changes);
    expect([replay.tabIndex, changes.tabIndex, diag.tabIndex]).toEqual([-1, 0, -1]);
    fireEvent.keyDown(changes, { key: "ArrowRight" });
    expect(diag.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(diag, { key: "ArrowRight" });                                // wraps round
    expect(replay.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(replay, { key: "End" });
    expect(diag.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(diag, { key: "Home" });
    expect(replay.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(replay, { key: "ArrowLeft" });
    expect(diag.getAttribute("aria-selected")).toBe("true");
  });
});

describe("the tab speaks every language", () => {
  it("has its words in all six", () => {
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of ["changesTab", "noChanges", "changesWhenDone", "changesSaving", "changesExpired", "changesNotSaved",
        "changesLoading", "changesFailed", "changesInterrupted", "changesNotYet"]) {
        const value = i18n.getResource(language, "translation", `activityPage.${key}`);
        expect(typeof value === "string" && value.length > 0, `${language} ${key}`).toBe(true);
      }
    }
  });
});

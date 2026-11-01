/**
 * INB7-c3 (v0.1.64): board F's 「改动」 tab in the inspector. It lists what the picked run changed in your folders, read from the
 * run's own conversation (GET /conversations/{id}/changes, the Overview's source), and a text path opens the DIFF1 side-by-side
 * reader in place, as it does from the Overview. A turn that was undone lists its paths without opening them.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const { getUsageSummary, listRuns, runProcess, runCounts, request, changes, changeDiff } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), runCounts: vi.fn(), request: vi.fn(), changes: vi.fn(),
  changeDiff: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: { getUsageSummary, listRuns, runProcess, runCounts }, request,
}));
vi.mock("../api/files", async (importOriginal) => {
  const real = await importOriginal<typeof import("../api/files")>();
  return { ...real, filesApi: { ...real.filesApi, changes, changeDiff } };
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
const run = (id: number, conversation: string) => ({
  id, spawn_id: null, spawn_name: "Arslan", status: "recorded", overall_score: null, overall_badge: null, total_ms: 60_000,
  user_message: `Run ${id}`, created_at: naive(T0 + id * HOUR), origin: "chat", model: "m", tokens: 1, conversation });
const RUNS = [run(12, "chat-b"), run(11, "chat-a")];
const process = (id: number, conversation: string) => ({ run_id: id, status: "recorded", conversation_id: conversation, entries: [
  { kind: "tool", tool: "write_file", ok: true, ms: 10, args_summary: '{"path": "notes.md"}', summary: "ok", at: null }] });
const TURNS = { turns: [
  { run_id: 13, at: null, undone: false, paths: [{ folder: "/Users/a/Notes", path: "newer-turn.md", kind: "edited" }] },
  { run_id: 11, at: null, undone: false, paths: [{ folder: "/Users/a/Notes", path: "notes.md", kind: "edited" },
    { folder: "/Users/a/Notes", path: "drafts/plan.md", kind: "made" }, { folder: "/Users/a/Notes", path: "old.png", kind: "deleted" }] },
  { run_id: 9, at: null, undone: false, paths: [{ folder: "/Users/a/Notes", path: "someone-else.md", kind: "edited" }] },
] };
const DIFF = { reason: null, kind: "edited", added: 1, removed: 1, since: false,
  lines: [[" ", 1, 1, "# Notes"], ["-", 2, null, "old line"], ["+", null, 2, "new line"]] };
const waiting = () => ({ count: 0, conversations: [], projects: [], scheduled: [], loaded: true });
const inspector = () => screen.getByTestId("run-inspector");
const tab = (name: RegExp) => within(inspector()).getByRole("tab", { name });

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue(RUNS);
  runCounts.mockReturnValue(new Promise(() => {}));
  runProcess.mockImplementation((id: number) => Promise.resolve(process(id, id === 11 ? "chat-a" : "chat-b")));
  changes.mockResolvedValue(TURNS);
  changeDiff.mockResolvedValue(DIFF);
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the 「改动」 tab", () => {
  it("lists only the picked run's paths, read from its own conversation", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(tab(/Changes/)).toHaveTextContent("3"));
    expect(tab(/Replay/).getAttribute("aria-selected")).toBe("true");          // the replay is the first tab, as on board F
    fireEvent.click(tab(/Changes/));
    expect(changes).toHaveBeenCalledWith("chat-a");
    const rows = within(inspector()).getAllByTestId("inspector-change");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("notes.md"), expect.stringContaining("plan.md"), expect.stringContaining("old.png")]);
    expect(within(inspector()).queryByText("someone-else.md")).toBeNull();
    expect(within(inspector()).queryByText("newer-turn.md")).toBeNull();
    expect(rows[0]).toHaveTextContent("Edited");
    expect(rows[1]).toHaveTextContent("Made");
  });

  it("opens a text path in the DIFF1 reader, and back to the list", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(tab(/Changes/)).toHaveTextContent("3"));
    fireEvent.click(tab(/Changes/));
    fireEvent.click(within(within(inspector()).getAllByTestId("inspector-change")[0]).getByRole("button"));
    await waitFor(() => expect(changeDiff).toHaveBeenCalledWith("chat-a", 11, "/Users/a/Notes", "notes.md"));
    expect(await within(inspector()).findByText("new line")).toBeTruthy();
    // An image has no line diff (DiffReader.opensDiff): listed, not opened.
    fireEvent.click(within(inspector()).getByTestId("diff-back"));                  // the reader's own Back
    const rows = within(inspector()).getAllByTestId("inspector-change");
    expect(within(rows[2]).queryByRole("button")).toBeNull();
  });

  it("lists an undone turn's paths without opening them", async () => {
    changes.mockResolvedValue({ turns: [{ ...TURNS.turns[1], undone: true }] });
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(tab(/Changes/)).toHaveTextContent("3"));
    fireEvent.click(tab(/Changes/));
    expect(within(inspector()).getByText("Undone")).toBeTruthy();
    expect(within(inspector()).getAllByTestId("inspector-change").every((row) => within(row).queryByRole("button") === null)).toBe(true);
  });

  it("says when the run changed no files", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-12"));
    await waitFor(() => expect(changes).toHaveBeenCalledWith("chat-b"));
    fireEvent.click(tab(/Changes/));
    expect(inspector()).toHaveTextContent("No files changed");
  });

  it("reads the changes again once the picked run ends (its checkpoint is written at the end)", async () => {
    runProcess.mockImplementation((id: number) => Promise.resolve({ ...process(id, "chat-a"), status: "recording", entries: [] }));
    changes.mockResolvedValue({ turns: [] });
    useActivityStore.setState({ range: "7d" });
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(changes).toHaveBeenCalledTimes(1));
    runProcess.mockImplementation((id: number) => Promise.resolve(process(id, "chat-a")));
    changes.mockResolvedValue(TURNS);
    window.dispatchEvent(new Event("arslan:proactive-changed"));
    await waitFor(() => expect(tab(/Changes/)).toHaveTextContent("3"));
  });

  it("a newly picked run opens on the replay again", async () => {
    render(<ActivityView waiting={waiting()} />);
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(tab(/Changes/)).toHaveTextContent("3"));
    fireEvent.click(tab(/Changes/));
    fireEvent.click(screen.getByTestId("activity-run-12"));
    await waitFor(() => expect(tab(/Replay/).getAttribute("aria-selected")).toBe("true"));
  });
});

describe("the tab speaks every language", () => {
  it("has its words in all six", () => {
    for (const language of SUPPORTED_LANGUAGES) {
      for (const key of ["changesTab", "noChanges"]) {
        const value = i18n.getResource(language, "translation", `activityPage.${key}`);
        expect(typeof value === "string" && value.length > 0, `${language} ${key}`).toBe(true);
      }
    }
  });
});

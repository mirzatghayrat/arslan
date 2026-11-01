/**
 * INB7-c5 (v0.1.64): board F's inspector shows what waits on you while no run is picked: each conversation, project and scheduled
 * task the badge counts, by name, with what it is and a way to open it where it waits. Picking a run shows that run instead; letting
 * it go comes back here. Why each one waits (#614's reasons) joins these rows once #614 is in.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { OPEN_SECTION_EVENT } from "../lib/sections";

const { getUsageSummary, listRuns, runProcess, runCounts, runChanges, listScheduledTasks, request } = vi.hoisted(() => ({
  getUsageSummary: vi.fn(), listRuns: vi.fn(), runProcess: vi.fn(), runCounts: vi.fn(), runChanges: vi.fn(),
  listScheduledTasks: vi.fn(), request: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  api: { getUsageSummary, listRuns, runProcess, runCounts, runChanges, listScheduledTasks,
    getRun: () => new Promise(() => {}), getRunAnomalies: () => new Promise(() => {}) }, request,
}));

import ActivityView from "../components/ActivityView";
import { useActivityStore } from "../stores/activityStore";

const T0 = 1_790_000_000;
const HOUR = 3600;
const naive = (sec: number) => new Date(sec * 1000).toISOString().replace("Z", "");
const summary = (range: string) => ({
  range, daily: [], not_covered: [], rows: [], estimated_any: false, tokens_total: 0, usd_total: 0,
  runs: { total: 1, done: 1, failed: 0, stopped: 0, running: 0, p50_ms: 1, p95_ms: 1 },
  bin_seconds: HOUR, duration_bands: ["<10s"],
  bins: Array.from({ length: 24 }, (_, i) => ({ start_ts: T0 + i * HOUR, runs: 0, failed: 0, tokens_total: 0, durations: [0] })),
});
const run = (id: number) => ({
  id, spawn_id: null, spawn_name: "Arslan", status: "recorded", overall_score: null, overall_badge: null, total_ms: 95_000,
  user_message: `Run ${id}`, created_at: naive(T0 + id * HOUR), origin: "chat", model: "m", tokens: 1 });
const THREADS = [{ id: "thread-a", title: "Compare floor prices" }, { id: "thread-b", title: "Not waiting" }];
const PROJECTS = [{ id: "p1", name: "Kitchen renovation" }];
const waiting = (over: Record<string, unknown> = {}) => ({ count: 3, conversations: ["thread-a"], projects: ["p1"], scheduled: [7],
  loaded: true, ...over });
const inspector = () => screen.getByTestId("run-inspector");
const rows = () => within(inspector()).queryAllByTestId(/^needs-row-/);

beforeEach(async () => {
  await i18n.changeLanguage("en");
  useActivityStore.setState({ range: "24h", filter: {}, openRunId: null, pickedRunId: null, pickedRun: null, replayStep: null,
    replayPlaying: false, scroll: {}, byModelOpen: false, modelSlots: {} });
  getUsageSummary.mockImplementation((range: string) => Promise.resolve(summary(range)));
  listRuns.mockResolvedValue([run(11)]);
  runCounts.mockReturnValue(new Promise(() => {}));
  runChanges.mockReturnValue(new Promise(() => {}));
  runProcess.mockResolvedValue({ run_id: 11, status: "scored", entries: [] });
  listScheduledTasks.mockResolvedValue([{ id: 7, name: "Weekly report" }, { id: 8, name: "Not waiting" }]);
  request.mockResolvedValue({ items: [], entries: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const view = (over: Record<string, unknown> = {}, props: Record<string, unknown> = {}) => {
  const onOpenConversation = vi.fn(); const onOpenProject = vi.fn();
  render(<ActivityView waiting={waiting(over)} threads={THREADS} projects={PROJECTS}
    onOpenConversation={onOpenConversation} onOpenProject={onOpenProject} {...props} />);
  return { onOpenConversation, onOpenProject };
};

describe("「要你做」 in the inspector while no run is picked", () => {
  it("lists each conversation, project and scheduled task that waits, by name, with what it is, and the count", async () => {
    view();
    await waitFor(() => expect(rows()).toHaveLength(3));
    const text = rows().map((r) => r.textContent);
    expect(text[0]).toContain("Compare floor prices"); expect(text[0]).toContain("Conversation");
    expect(text[1]).toContain("Kitchen renovation"); expect(text[1]).toContain("Project");
    expect(text[2]).toContain("Weekly report"); expect(text[2]).toContain("Scheduled task");
    expect(within(inspector()).getByTestId("needs-count")).toHaveTextContent("3");
    expect(within(inspector()).getByTestId("needs-panel")).toHaveAttribute("data-asking", "true");
    expect(inspector()).not.toHaveTextContent("Not waiting");
  });

  it("opens each where it waits: the conversation, the project, the Scheduled page", async () => {
    const { onOpenConversation, onOpenProject } = view();
    const opened: unknown[] = [];
    const onSection = (e: Event) => opened.push((e as CustomEvent).detail);
    window.addEventListener(OPEN_SECTION_EVENT, onSection);
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(within(rows()[0]).getByRole("button", { name: /Open/ }));
    fireEvent.click(within(rows()[1]).getByRole("button", { name: /Open/ }));
    fireEvent.click(within(rows()[2]).getByRole("button", { name: /Open/ }));
    window.removeEventListener(OPEN_SECTION_EVENT, onSection);
    expect(onOpenConversation).toHaveBeenCalledWith("thread-a");
    expect(onOpenProject).toHaveBeenCalledWith("p1");
    expect(opened).toEqual(["scheduled"]);
  });

  it("names what it cannot find by what it is, never by its id", async () => {
    view({ conversations: ["thread-gone"], projects: ["p-gone"], scheduled: [99] });
    await waitFor(() => expect(rows()).toHaveLength(3));
    const text = rows().map((r) => r.textContent ?? "");
    expect(text[0]).toContain("A conversation"); expect(text[1]).toContain("A project"); expect(text[2]).toContain("A scheduled task");
    expect(text.join(" ")).not.toMatch(/thread-gone|p-gone|99/);
  });

  it("says all is done only once the count has come back as none, and reads the tasks only when one waits", async () => {
    view({ count: 0, conversations: [], projects: [], scheduled: [] });
    expect(await within(inspector()).findByText(/All caught up/)).toBeTruthy();
    expect(within(inspector()).getByTestId("needs-panel")).toHaveAttribute("data-asking", "false");
    expect(listScheduledTasks).not.toHaveBeenCalled();
    cleanup();
    view({ count: 0, conversations: [], projects: [], scheduled: [], loaded: false });
    await screen.findByTestId("run-inspector");
    expect(inspector()).not.toHaveTextContent("All caught up");
  });

  it("gives way to a picked run, and comes back when the run is let go", async () => {
    view();
    await waitFor(() => expect(rows()).toHaveLength(3));
    fireEvent.click(await screen.findByTestId("activity-run-11"));
    await waitFor(() => expect(rows()).toHaveLength(0));
    fireEvent.click(within(inspector()).getByRole("button", { name: "Back to all runs" }));
    await waitFor(() => expect(rows()).toHaveLength(3));
  });
});

describe("the panel speaks every language", () => {
  it("has its words in all six", async () => {
    for (const lng of SUPPORTED_LANGUAGES) {
      await i18n.changeLanguage(lng);
      for (const key of ["needsConversation", "needsProject", "needsTask", "needsAConversation", "needsAProject", "needsATask", "needsOpen"]) {
        expect(i18n.exists(`activityPage.${key}`), `${lng}: ${key}`).toBe(true);
      }
    }
  });
});

/**
 * WB1-1 (v0.1.64, card docs/plans/0164/WB1-workbench.md): the workbench is a fixed row — Working
 * folder, Progress, Browser — with Task gone; Progress keeps its count while another tab is shown;
 * Working folder carries "Show in Finder"; the divider is a thin line that a mouse drag never lights.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, jobsApi } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), open: vi.fn(), reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn() },
  jobsApi: { list: vi.fn(), stop: vi.fn() },
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/tasks", () => ({ backgroundJobsApi: jobsApi }));
vi.mock("../components/BrowserReader", () => ({ default: () => <div data-testid="browser-reader" /> }));

import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useWorkbench } from "../stores/workbenchStore";
import Workbench from "../components/workbench/Workbench";

const job = (id: string, phase = "running") => ({ job_id: id, goal: `Goal ${id}`, phase, step: null });
const mount = () => render(<Workbench conversationId="c1" taskId={null} temporary={false} />);

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: false, tab: "files", reader: null, folder: null });
  files.home.mockResolvedValue({ path: "~/Arslan", project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  files.list.mockResolvedValue({ path: "~/Arslan", root: "~/Arslan", crumbs: [{ name: "Arslan", path: "~/Arslan" }], total: 0, more: false, entries: [] });
  jobsApi.list.mockResolvedValue({ jobs: [] });
  jobsApi.stop.mockResolvedValue({});
  try { localStorage.clear(); } catch { /* storage off */ }
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the row", () => {
  it("is Working folder, Progress, Browser, in that order, and Task is gone", () => {
    useWorkbench.getState().show();
    mount();
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs.map((tab) => tab.getAttribute("data-testid")))
      .toEqual(["workbench-tab-files", "workbench-tab-progress", "workbench-tab-browser"]);
    expect(tabs.map((tab) => tab.textContent)).toEqual(["workbench.folder", "workbench.progress", "workbench.browser"]);
    expect(screen.queryByTestId("workbench-tab-task")).toBeNull();
  });

  it("opens on Working folder by default, from a fresh store", async () => {
    vi.resetModules();
    const { useWorkbench: fresh } = await import("../stores/workbenchStore");
    expect(fresh.getState().tab).toBe("files");
  });

  it("keeps every fixed tab whether or not a job runs", async () => {
    useWorkbench.getState().show();
    mount();
    await waitFor(() => expect(jobsApi.list).toHaveBeenCalledWith("c1"));
    expect(screen.getByTestId("workbench-tab-progress")).toBeInTheDocument();
    expect(screen.getByTestId("workbench-tab-browser")).toBeInTheDocument();
  });
});

describe("Progress", () => {
  it("shows the running count while Working folder is selected, and lists the jobs with stop", async () => {
    jobsApi.list.mockResolvedValue({ jobs: [job("a"), job("b"), job("c", "finished")] });
    useWorkbench.getState().show("files");
    mount();
    expect(await screen.findByTestId("workbench-progress-count")).toHaveTextContent("2");
    expect(screen.getByTestId("files-tab")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workbench-tab-progress"));
    const tab = screen.getByTestId("progress-tab");
    expect(tab).toHaveTextContent("Goal a");
    expect(tab).not.toHaveTextContent("Goal c");                       // finished jobs are not "running"
    fireEvent.click(within(tab).getAllByRole("button", { name: /workbench.stop/ })[0]);
    await waitFor(() => expect(jobsApi.stop).toHaveBeenCalledWith("a"));
  });

  it("says nothing is running, with no count, when no job runs", async () => {
    useWorkbench.getState().show("progress");
    mount();
    expect(await screen.findByTestId("progress-empty")).toHaveTextContent("workbench.nothingRunning");
    expect(screen.queryByTestId("workbench-progress-count")).toBeNull();
  });

  it("updates its count while another tab is selected", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      useWorkbench.getState().show("browser");
      mount();
      await waitFor(() => expect(jobsApi.list).toHaveBeenCalled());
      expect(screen.queryByTestId("workbench-progress-count")).toBeNull();
      jobsApi.list.mockResolvedValue({ jobs: [job("a")] });
      await act(async () => { vi.advanceTimersByTime(5_100); });
      expect(await screen.findByTestId("workbench-progress-count")).toHaveTextContent("1");
    } finally { vi.useRealTimers(); }
  });
});

describe("Working folder and Browser", () => {
  it("has the folder bar with Show in Finder", async () => {
    useWorkbench.getState().show("files");
    mount();
    const bar = await screen.findByTestId("files-folderbar");
    expect(bar).toHaveTextContent("~/Arslan");
    fireEvent.click(within(bar).getByTestId("files-reveal"));
    expect(files.reveal).toHaveBeenCalledWith("~/Arslan");
  });

  it("Browser starts with today's empty state and New browser tab", () => {
    useWorkbench.getState().show("browser");
    mount();
    const dock = screen.getByTestId("dock-embedded");
    expect(dock).toHaveTextContent("dock.empty");
    expect(within(dock).getAllByRole("button", { name: /dock.newBrowser/ }).length).toBeGreaterThan(0);
  });
});

describe("the look", () => {
  it("the divider never turns a colour: no primary background in any state, and only a keyboard focus shows a ring", () => {
    useWorkbench.getState().show();
    mount();
    const cls = screen.getByRole("separator").className;
    expect(cls).not.toMatch(/bg-primary/);
    expect(cls).not.toMatch(/(^|\s)focus:/);                            // focus-visible only: a mouse drag leaves it unlit
    expect(cls).toMatch(/focus-visible:/);
  });

  it("headings are sentence case, not all caps", async () => {
    jobsApi.list.mockResolvedValue({ jobs: [job("a")] });
    useWorkbench.getState().show("progress");
    mount();
    await screen.findByText("Goal a");
    for (const h of screen.getAllByRole("heading")) expect(h.className).not.toMatch(/uppercase|tracking-wider/);
  });
});

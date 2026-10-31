/**
 * DIFF2-2 (v0.1.64; the user's picks on the DIFF2-0 mock, 2026-10-31): Overview's Changes for a folder in a git repo.
 * The branch against its base, its PRs with their checks (a PR opens in the workbench's Browser tab), the commits
 * (folded) and the files changed since the branch left its base, committed or not; a text file opens DiffReader.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, jobsApi, mcp, client, conv } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), open: vi.fn(), reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn(),
    changes: vi.fn(), changeDiff: vi.fn(), repoChanges: vi.fn(), repoDiff: vi.fn() },
  jobsApi: { list: vi.fn(), stop: vi.fn() },
  mcp: { listMcpServers: vi.fn(), reconnectMcpServer: vi.fn() },
  client: { fetchProviderModels: vi.fn(), updateProviderConfig: vi.fn(), api: { runCheckpoint: vi.fn(), undoTurn: vi.fn() } },
  conv: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/tasks", () => ({ backgroundJobsApi: jobsApi }));
vi.mock("../api/mcp", () => mcp);
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), ...client }));
vi.mock("../api/conversationModel", () => ({ conversationModelApi: conv }));
vi.mock("../components/BrowserReader", () => ({
  default: ({ startUrl }: { startUrl?: string }) => <div data-testid="browser-reader" data-start={startUrl ?? ""} />,
}));

import type { RepoChanges } from "../api/files";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useSettingsStore } from "../stores/settingsStore";
import { MAX_WIDTH, useWorkbench } from "../stores/workbenchStore";
import Workbench from "../components/workbench/Workbench";
import { DOCK_KEY } from "../lib/workDock";

const onOpenSettings = vi.fn();
const mount = () => render(<Workbench conversationId="c1" taskId={null} temporary={false} onOpenSettings={onOpenSettings} />);
const REPO: RepoChanges = {
  branch: "dark-mode", detached: null, base: "main",
  commits: [{ sha: "9f3c2a1", subject: "Kyoto day 2" }, { sha: "4b7e0d8", subject: "Build: sorted pages" }],
  files: [
    { path: "src/styles/theme.css", kind: "edited", uncommitted: true, added: 8, removed: 0 },
    { path: "content/kyoto.md", kind: "edited", uncommitted: false, added: 3, removed: 2 },
    { path: "public/map.png", kind: "made", uncommitted: false, added: null, removed: null },
  ],
  more: 0, signed_in: true, github: "someone/journal",
  prs: [
    { number: 42, title: "Dark mode for the journal", state: "open", draft: false, url: "https://github.com/someone/journal/pull/42", checks: "passed" },
    { number: 38, title: "First try", state: "closed", draft: false, url: null, checks: null },
  ],
};

beforeEach(() => {
  try { localStorage.removeItem(DOCK_KEY); } catch { /* storage off */ }
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: false, tab: "overview", reader: null, folder: null, width: 380, pendingUrl: null });
  useSettingsStore.setState({ settings: {} } as never);
  files.home.mockResolvedValue({ path: "~/Code/journal", project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  jobsApi.list.mockResolvedValue({ jobs: [] });
  mcp.listMcpServers.mockResolvedValue([]);
  conv.get.mockResolvedValue({ choice: null });
  files.changes.mockResolvedValue({ turns: [] });
  files.repoChanges.mockResolvedValue({ repo: REPO });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("a repo folder in Overview's Changes", () => {
  it("shows the branch against its base, the totals, and each file with its uncommitted tag", async () => {
    useWorkbench.getState().show("overview");
    mount();
    const repo = await screen.findByTestId("overview-repo");
    expect(within(repo).getByTestId("repo-branch")).toHaveTextContent("dark-mode");
    expect(repo).toHaveTextContent("main");
    expect(repo).toHaveTextContent('workbench.repoAhead:{"count":2}');
    expect(within(repo).getByTestId("repo-totals")).toHaveTextContent("+11 −2");
    expect(within(repo).getAllByTestId("repo-uncommitted")).toHaveLength(1);
    expect(within(repo).getAllByTestId("repo-file-open")).toHaveLength(2);           // the png has no line diff
  });

  it("a text file opens its diff in DiffReader at the panel's full width", async () => {
    files.repoDiff.mockResolvedValue({ reason: null, kind: "edited", added: 1, removed: 0, since: false,
      lines: [[" ", 1, 1, ":root {"], ["+", null, 2, "  --paper: #16161a;"]] });
    useWorkbench.getState().show("overview");
    mount();
    fireEvent.click((await screen.findAllByTestId("repo-file-open"))[0]);
    const reader = await screen.findByTestId("diff-reader");
    expect(files.repoDiff).toHaveBeenCalledWith("c1", "src/styles/theme.css");
    expect(files.changeDiff).not.toHaveBeenCalled();
    expect(await within(reader).findByTestId("diff-row-changed")).toHaveTextContent("--paper: #16161a;");
    expect(screen.getByTestId("workbench")).toHaveStyle({ width: `${MAX_WIDTH}px` });
  });

  it("PR rows show state and checks; one with a link opens in the Browser tab, one without is a plain row", async () => {
    useWorkbench.getState().show("overview");
    mount();
    const prs = await screen.findAllByTestId("repo-pr");
    expect(prs[0]).toHaveTextContent("#42");
    expect(prs[0]).toHaveTextContent("workbench.pr_open");
    expect(within(prs[0]).getByTestId("repo-pr-checks")).toHaveTextContent("workbench.checks_passed");
    expect(within(prs[1]).queryByTestId("repo-pr-open")).toBeNull();
    fireEvent.click(within(prs[0]).getByTestId("repo-pr-open"));
    await waitFor(() => expect(useWorkbench.getState().tab).toBe("browser"));
    expect((await screen.findByTestId("browser-reader")).dataset.start).toBe("https://github.com/someone/journal/pull/42");
    expect(useWorkbench.getState().pendingUrl).toBeNull();                          // taken once
    expect(localStorage.getItem(DOCK_KEY) ?? "").not.toContain("github.com");     // the address is never saved
  });

  it("commits are folded until asked", async () => {
    useWorkbench.getState().show("overview");
    mount();
    fireEvent.click(await screen.findByTestId("repo-commits-toggle"));
    expect(screen.getByTestId("repo-commits")).toHaveTextContent("Kyoto day 2");
  });

  it("signed out of GitHub: the sign-in line opens Settings' connections", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, signed_in: false, prs: [] } });
    useWorkbench.getState().show("overview");
    mount();
    const line = await screen.findByTestId("repo-signin");
    fireEvent.click(within(line).getByRole("button"));
    expect(onOpenSettings).toHaveBeenCalledWith("connections");
  });

  it("GitHub not answering is said, and is not the repo's error", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, prs: [], prs_error: "unavailable" } });
    useWorkbench.getState().show("overview");
    mount();
    expect(await screen.findByText("workbench.repoPrsUnavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("repo-error")).toBeNull();
    expect(screen.getByTestId("repo-files")).toBeInTheDocument();
  });

  it("a repo not on GitHub shows no PR part at all", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, github: null, signed_in: null, prs: [] } });
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-repo");
    expect(screen.queryByText("workbench.repoPrs")).toBeNull();
    expect(screen.queryByTestId("repo-signin")).toBeNull();
  });

  it("no git, or nothing changed, says so in a sentence", async () => {
    files.repoChanges.mockResolvedValue({ repo: { error: "no_git" } as RepoChanges });
    useWorkbench.getState().show("overview");
    const { unmount } = mount();
    expect(await screen.findByTestId("repo-error")).toHaveTextContent("workbench.repoNoGit");
    unmount();
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, files: [], commits: [] } });
    mount();
    expect(await screen.findByText("workbench.repoNothing")).toBeInTheDocument();
  });

  it("a folder that isn't a repo keeps DIFF1's per-turn list and shows no repo part", async () => {
    files.repoChanges.mockResolvedValue({ repo: null });
    files.changes.mockResolvedValue({ turns: [{ run_id: 7, at: null, undone: false,
      paths: [{ folder: "/x", path: "a.md", kind: "edited" }] }] });
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-turn-7");
    expect(screen.queryByTestId("overview-repo")).toBeNull();
  });
});

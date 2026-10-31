/**
 * DIFF2-2 (v0.1.64; the user's picks on the DIFF2-0 mock, 2026-10-31): Overview's Changes for a folder in a git repo.
 * The branch against its base, its PRs with their checks (a PR opens in the workbench's Browser tab), the commits
 * (folded) and the files changed since the branch left its base, committed or not; a text file opens DiffReader.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import { prLink } from "../components/workbench/RepoChanges";

const RLO = String.fromCharCode(0x202e), LRI = String.fromCharCode(0x2066);
const FSI = String.fromCharCode(0x2068), PDI = String.fromCharCode(0x2069);
const REORDER = /[\u202A-\u202E\u2066\u2067\u200E\u200F\u061C]/;

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
    { number: 42, title: "Dark mode for the journal", state: "open", draft: false, url: "https://elsewhere.example/x", checks: "passed" },
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
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

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

  it("PR rows show state and checks; a PR opens github.com's page for its number in the Browser tab, whatever link came with it", async () => {
    useWorkbench.getState().show("overview");
    mount();
    const prs = await screen.findAllByTestId("repo-pr");
    expect(prs[0]).toHaveTextContent("#42");
    expect(prs[0]).toHaveTextContent("workbench.pr_open");
    expect(within(prs[0]).getByTestId("repo-pr-checks")).toHaveTextContent("workbench.checks_passed");
    expect(within(prs[1]).getByTestId("repo-pr-open")).toBeInTheDocument();          // built from the slug, not gh's url
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

  it("signed out of GitHub: one line saying how gh signs in, not a link to Settings, which can't", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, signed_in: false, prs: [] } });
    useWorkbench.getState().show("overview");
    mount();
    const line = await screen.findByTestId("repo-signin");
    expect(line).toHaveTextContent("workbench.repoSignIn");
    expect(within(line).queryByRole("button")).toBeNull();
    expect(onOpenSettings).not.toHaveBeenCalled();
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

  it("an error key that isn't git's (gh's, or an unknown one) never hides the repo (#588 review, F1)", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, prs: [], error: "unavailable" } as unknown as RepoChanges });
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-repo");
    expect(screen.queryByTestId("repo-error")).toBeNull();
    expect(screen.getByTestId("repo-files")).toBeInTheDocument();
  });

  it("a detached HEAD on GitHub has no PR part and no sign-in line", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, branch: null, detached: "abc1234", signed_in: null, prs: [] } });
    useWorkbench.getState().show("overview");
    mount();
    const repo = await screen.findByTestId("overview-repo");
    expect(within(repo).getByTestId("repo-branch")).toHaveTextContent('workbench.repoDetached:{"sha":"abc1234"}');
    expect(screen.queryByText("workbench.repoPrs")).toBeNull();
    expect(screen.queryByText("workbench.repoNoPr")).toBeNull();
  });

  it("a PR state GitHub doesn't send gets no pill", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, prs: [{ ...REPO.prs[0], state: "weird" as never }] } });
    useWorkbench.getState().show("overview");
    mount();
    const pr = await screen.findByTestId("repo-pr");
    expect(pr).not.toHaveTextContent("workbench.pr_");
  });
});

describe("outside text (#588 review, F2 and F3)", () => {
  it("branch, base, PR title, commit subject, file name, folder and title attribute: isolated, no reordering control left", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO,
      branch: `feat${RLO}gnp.exe`, base: `ma${LRI}in${PDI}`,
      commits: [{ sha: "9f3c2a1", subject: `fix ${RLO}lave` }],
      files: [{ path: `di${RLO}r/na${RLO}me.ts`, kind: "edited", uncommitted: false, added: 1, removed: 0 }],
      prs: [{ ...REPO.prs[0], title: `Title ${RLO}gnp` }] } });
    useWorkbench.getState().show("overview");
    mount();
    const repo = await screen.findByTestId("overview-repo");
    fireEvent.click(within(repo).getByTestId("repo-commits-toggle"));
    expect(repo.textContent).not.toMatch(REORDER);
    expect(within(repo).getByTestId("repo-branch").textContent).toContain(`${FSI}featgnp.exe${PDI}`);
    expect(repo.textContent).toContain(`${FSI}main${PDI}`);
    expect(within(repo).getByTestId("repo-pr").textContent).toContain(`${FSI}Title gnp${PDI}`);
    expect(within(repo).getByTestId("repo-commits").textContent).toContain(`${FSI}fix lave${PDI}`);
    const file = within(repo).getByTestId("repo-files");
    expect(file.textContent).toContain(`${FSI}name.ts${PDI}`);
    expect(file.textContent).toContain(`${FSI}dir/${PDI}`);
    expect(file.querySelector("li")!.getAttribute("title")).not.toMatch(REORDER);
  });

  it("a diff line's bidi controls are shown as markers, not applied", async () => {
    files.repoDiff.mockResolvedValue({ reason: null, kind: "edited", added: 1, removed: 0, since: false,
      lines: [["+", null, 1, `if (isAdmin) { ${RLO} } ${LRI}// check later${PDI}`]] });
    useWorkbench.getState().show("overview");
    mount();
    fireEvent.click((await screen.findAllByTestId("repo-file-open"))[0]);
    const row = await screen.findByTestId("diff-row-changed");
    expect(row.textContent).not.toMatch(REORDER);
    expect(within(row).getAllByTestId("escaped-control").map((e) => e.textContent)).toEqual(["U+202E", "U+2066", "U+2069"]);
  });

  it("the reader's subtitle is the folder's name and the repo path's folder, not the two joined", async () => {
    files.repoDiff.mockResolvedValue({ reason: null, kind: "edited", added: 0, removed: 0, since: false, lines: [] });
    useWorkbench.getState().show("overview");
    mount();
    fireEvent.click((await screen.findAllByTestId("repo-file-open"))[0]);
    const reader = await screen.findByTestId("diff-reader");
    expect(reader).toHaveTextContent(`journal · src/styles`);
    expect(reader.textContent).not.toContain("journal/src");
  });

  it("a repo file no longer listed says so, not DIFF1's turn sentence", async () => {
    const { ApiError } = await import("../api/client");
    files.repoDiff.mockRejectedValue(new ApiError("x", 404));
    useWorkbench.getState().show("overview");
    mount();
    fireEvent.click((await screen.findAllByTestId("repo-file-open"))[0]);
    expect(await screen.findByTestId("diff-note")).toHaveTextContent("workbench.diffGoneRepo");
  });
});

describe("the PR link (#588 review, F6)", () => {
  it.each([["someone/journal", 42, "https://github.com/someone/journal/pull/42"], [null, 42, null], ["a/b/c", 1, null],
    ["evil.com/x?y", 1, null], ["someone/journal", 0, null], ["someone/journal", 1.5, null]])(
    "prLink(%s, %s) is %s", (slug, n, out) => { expect(prLink(slug as string | null, n as number)).toBe(out); });
});

describe("polling and switching (#588 review, F3, F4, F8)", () => {
  it("the 10 s poll asks again while shown and stops after unmount", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    useWorkbench.getState().show("overview");
    const view = mount();
    await screen.findByTestId("overview-repo");
    const first = files.repoChanges.mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(10_000); });
    await waitFor(() => expect(files.repoChanges.mock.calls.length).toBeGreaterThan(first));
    view.unmount();
    const after = files.repoChanges.mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(files.repoChanges.mock.calls.length).toBe(after);
  });

  it("an answer still coming is not asked for again, and chat items don't ask at all", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    files.repoChanges.mockReturnValue(new Promise(() => {}));
    useWorkbench.getState().show("overview");
    mount();
    await waitFor(() => expect(files.repoChanges).toHaveBeenCalledTimes(1));
    for (let i = 0; i < 3; i++) await act(async () => { vi.advanceTimersByTime(10_000); });
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        useArslanStore.setState({ items: [...useArslanStore.getState().items, { id: `i${i}`, kind: "text", role: "assistant", text: "x" } as never] });
      });
    }
    expect(files.repoChanges).toHaveBeenCalledTimes(1);
  });

  it("after a switch the other conversation's repo is never drawn, and its late answer is dropped", async () => {
    let lateC1: (v: { repo: RepoChanges }) => void = () => {};
    const seen: string[] = [];
    useWorkbench.getState().show("overview");
    const view = mount();
    await screen.findByTestId("overview-repo");
    files.repoChanges.mockImplementation((id: string) => id === "c1"
      ? new Promise((resolve) => { lateC1 = resolve; }) : new Promise(() => {}));
    const observer = new MutationObserver(() => {
      const branch = document.querySelector("[data-testid=repo-branch]");
      if (branch) seen.push(branch.textContent ?? "");
    });
    view.rerender(<Workbench conversationId="c2" taskId={null} temporary={false} onOpenSettings={onOpenSettings} />);
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    expect(screen.queryByTestId("overview-repo")).toBeNull();                         // the first render already
    await waitFor(() => expect(files.repoChanges).toHaveBeenLastCalledWith("c2"));
    await act(async () => { lateC1({ repo: { ...REPO, branch: "c1-late" } }); await new Promise((r) => setTimeout(r, 0)); });
    observer.disconnect();
    expect(screen.queryByTestId("overview-repo")).toBeNull();
    expect(seen).toEqual([]);
  });

  it("an open diff closes when the conversation changes", async () => {
    files.repoDiff.mockResolvedValue({ reason: null, kind: "edited", added: 1, removed: 0, since: false,
      lines: [["+", null, 1, "from c1's repo"]] });
    useWorkbench.getState().show("overview");
    const view = mount();
    fireEvent.click((await screen.findAllByTestId("repo-file-open"))[0]);
    await screen.findByText("from c1's repo");
    view.rerender(<Workbench conversationId="c2" taskId={null} temporary={false} onOpenSettings={onOpenSettings} />);
    await waitFor(() => expect(screen.queryByTestId("diff-reader")).toBeNull());
  });
});

describe("a repo folder and a plain folder (#588 review, F7)", () => {
  it("a turn's edit in the repo shows once, in the repo's list; its edit in another folder keeps DIFF1's row", async () => {
    files.repoChanges.mockResolvedValue({ repo: { ...REPO, files: [REPO.files[0]] } });
    files.changes.mockResolvedValue({ turns: [{ run_id: 7, at: null, undone: false, paths: [
      { folder: "/Users/u/Code/journal", path: "src/styles/theme.css", kind: "edited" },
      { folder: "/Users/u/Arslan/Photo backups", path: "plans/backup-plan.md", kind: "edited" }] }] });
    useWorkbench.getState().show("overview");
    mount();
    const turn = await screen.findByTestId("overview-turn-7");
    expect(turn).toHaveTextContent("backup-plan.md");
    expect(turn).not.toHaveTextContent("theme.css");
    const section = screen.getByTestId("overview-changes");
    expect(within(section).getAllByText((_, el) => el?.tagName === "SPAN" && (el.textContent ?? "") === `${FSI}theme.css${PDI}`))
      .toHaveLength(1);
  });

  it("a turn whose every path is in the repo isn't listed at all", async () => {
    files.changes.mockResolvedValue({ turns: [{ run_id: 7, at: null, undone: false,
      paths: [{ folder: "/Users/u/Code/journal", path: "src/styles/theme.css", kind: "edited" }] }] });
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-repo");
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(screen.queryByTestId("overview-turn-7")).toBeNull();
  });
});

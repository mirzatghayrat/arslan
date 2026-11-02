/**
 * DIFF1 web half (v0.1.64; the user, 2026-10-31: side by side, and made or deleted files open too): a text path in
 * Overview's Changes opens the reader with the turn's line diff, the saved copy on the left and the file now on the
 * right, unchanged runs folded. Files that have no line diff (images, PDFs, office files) stay plain rows.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, jobsApi, mcp, client, conv } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), open: vi.fn(), reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn(),
    changes: vi.fn(), changeDiff: vi.fn() },
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
vi.mock("../components/BrowserReader", () => ({ default: () => <div data-testid="browser-reader" /> }));

import type { ChangeDiffLine } from "../api/files";
import { ApiError } from "../api/client";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useSettingsStore } from "../stores/settingsStore";
import { MAX_WIDTH, useWorkbench } from "../stores/workbenchStore";
import Workbench from "../components/workbench/Workbench";
import { CONTEXT, segments, sideBySide } from "../components/workbench/DiffReader";

const FOLDER = "/Users/someone/Arslan";
const mount = () => render(<Workbench conversationId="c1" taskId={null} temporary={false} />);
const turn = (paths: [string, string][], undone = false) => ({ turns: [{ run_id: 7, at: "2026-10-31T09:31:00Z", undone,
  paths: paths.map(([kind, path]) => ({ folder: FOLDER, path, kind })) }] });
const diffOf = (lines: ChangeDiffLine[], extra: object = {}) => ({ reason: null, kind: "edited", since: false, lines,
  added: lines.filter((l) => l[0] === "+").length, removed: lines.filter((l) => l[0] === "-").length, ...extra });
const same = (from: number, count: number, shift = 0): ChangeDiffLine[] =>
  Array.from({ length: count }, (_, i) => [" ", from + i, from + i + shift, `line ${from + i}`]);

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: false, tab: "overview", reader: null, folder: null, width: 380 });
  useSettingsStore.setState({ settings: {} } as never);
  files.home.mockResolvedValue({ path: "~/Arslan", project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  jobsApi.list.mockResolvedValue({ jobs: [] });
  mcp.listMcpServers.mockResolvedValue([]);
  conv.get.mockResolvedValue({ choice: null });
  files.changes.mockResolvedValue({ turns: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("sideBySide", () => {
  it("pairs a removed run with the added run after it, keeps the rest one-sided, and both sides for unchanged", () => {
    const rows = sideBySide([[" ", 1, 1, "a"], ["-", 2, null, "b"], ["-", 3, null, "c"], ["+", null, 2, "B"], [" ", 4, 3, "d"],
      ["+", null, 4, "e"]]);
    expect(rows).toEqual([
      { left: [1, "a"], right: [1, "a"], changed: false },
      { left: [2, "b"], right: [2, "B"], changed: true },
      { left: [3, "c"], right: null, changed: true },
      { left: [4, "d"], right: [3, "d"], changed: false },
      { left: null, right: [4, "e"], changed: true },
    ]);
  });

  it("a made file is all right-hand rows; a deleted one all left-hand", () => {
    expect(sideBySide([["+", null, 1, "x"], ["+", null, 2, "y"]]).map((r) => [r.left, r.right]))
      .toEqual([[null, [1, "x"]], [null, [2, "y"]]]);
    expect(sideBySide([["-", 1, null, "x"]]).map((r) => [r.left, r.right])).toEqual([[[1, "x"], null]]);
  });
});

describe("segments", () => {
  it(`folds an unchanged run beyond ${CONTEXT} lines of context on each side of a change`, () => {
    const rows = sideBySide([...same(1, 10), ["-", 11, null, "old"], ["+", null, 11, "new"], ...same(12, 10)]);
    expect(segments(rows)).toEqual([
      { fold: true, from: 0, to: 10 - CONTEXT }, { fold: false, from: 10 - CONTEXT, to: 11 + CONTEXT },
      { fold: true, from: 11 + CONTEXT, to: 21 },
    ]);
  });

  it("does not fold a run no longer than the context it would leave, nor anything in a file with no unchanged run", () => {
    const rows = sideBySide([...same(1, CONTEXT + 1), ["+", null, CONTEXT + 2, "x"]]);
    expect(segments(rows)).toEqual([{ fold: false, from: 0, to: rows.length }]);
    expect(segments(sideBySide([["+", null, 1, "x"]]))).toEqual([{ fold: false, from: 0, to: 1 }]);
  });
});

describe("Changes opens the diff", () => {
  it("an Edited text path opens the reader beside the saved copy, wider, with the counts and folds", async () => {
    files.changes.mockResolvedValue(turn([["edited", "plans/backup-plan.md"]]));
    files.changeDiff.mockResolvedValue(diffOf([...same(1, 10), ["-", 11, null, "Not decided yet."],
      ["+", null, 11, "Time Machine plus iCloud Photos."], ...same(12, 2)]));
    useWorkbench.getState().show("overview");
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /backup-plan\.md/ }));
    const reader = await screen.findByTestId("diff-reader");
    expect(files.changeDiff).toHaveBeenCalledWith("c1", 7, FOLDER, "plans/backup-plan.md");
    expect(within(reader).getByTestId("diff-counts")).toHaveTextContent("+1 −1");
    const changed = await within(reader).findAllByTestId("diff-row-changed");
    expect(changed).toHaveLength(1);
    expect(within(changed[0]).getByTestId("diff-left")).toHaveTextContent("Not decided yet.");
    expect(within(changed[0]).getByTestId("diff-right")).toHaveTextContent("Time Machine plus iCloud Photos.");
    expect(screen.getByTestId("workbench")).toHaveStyle({ width: `${MAX_WIDTH}px` });     // two columns need the room
    const fold = within(reader).getByTestId("diff-fold");
    expect(fold).toHaveTextContent(`workbench.diffUnchanged:{"count":${10 - CONTEXT}}`);
    fireEvent.click(fold);
    expect(within(reader).queryByTestId("diff-fold")).toBeNull();
    expect(within(reader).getAllByText("line 1")).toHaveLength(2);                // both sides, once unfolded
    fireEvent.click(within(reader).getByTestId("diff-back"));
    await waitFor(() => expect(screen.queryByTestId("diff-reader")).toBeNull());
  });

  it("Made and Deleted text files open too (the user's pick); an image, a PDF or a spreadsheet stays a plain row", async () => {
    files.changes.mockResolvedValue(turn([["made", "notes/new.md"], ["deleted", "old.txt"], ["made", "check.png"],
      ["edited", "budget.xlsx"], ["edited", "scan.pdf"]]));
    files.changeDiff.mockResolvedValue(diffOf([["+", null, 1, "fresh"]], { kind: "made" }));
    useWorkbench.getState().show("overview");
    mount();
    expect(await screen.findByRole("button", { name: /new\.md/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /old\.txt/ })).toBeInTheDocument();
    for (const name of [/check\.png/, /budget\.xlsx/, /scan\.pdf/]) expect(screen.queryByRole("button", { name })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /new\.md/ }));
    const row = await screen.findByTestId("diff-row-changed");
    expect(within(row).getByTestId("diff-left")).toHaveTextContent("");
    expect(within(row).getByTestId("diff-right")).toHaveTextContent("fresh");
  });

  it("an undone turn's paths stay plain rows", async () => {
    files.changes.mockResolvedValue(turn([["edited", "a.md"]], true));
    useWorkbench.getState().show("overview");
    mount();
    await screen.findByTestId("overview-turn-7");
    expect(screen.queryByRole("button", { name: /a\.md/ })).toBeNull();
  });
});

describe("the diff reader's notes", () => {
  const open = async () => {
    useWorkbench.getState().openReader({ kind: "diff", conversationId: "c1", runId: 7, folder: FOLDER, path: "a.md" });
    mount();
    return screen.findByTestId("diff-reader");
  };

  it.each([["not_text"], ["too_big"], ["copy_changed"]])("says why there are no lines (%s)", async (reason) => {
    files.changeDiff.mockResolvedValue({ ...diffOf([]), reason, kind: null });
    const reader = await open();
    expect(await within(reader).findByTestId("diff-note")).toHaveTextContent(`workbench.diff_${reason}`);
  });

  it("says when the file changed again after the turn", async () => {
    files.changeDiff.mockResolvedValue(diffOf([["+", null, 1, "x"]], { since: true }));
    const reader = await open();
    expect(await within(reader).findByTestId("diff-since")).toHaveTextContent("workbench.diffSince");
  });

  it.each([[404, "workbench.diffGone"], [403, "workbench.diffHidden"], [500, "workbench.diffFailed"]])(
    "a %i is a plain sentence, not a crash", async (status, key) => {
      files.changeDiff.mockRejectedValue(new ApiError("x", status));
      const reader = await open();
      expect(await within(reader).findByTestId("diff-note")).toHaveTextContent(key);
    });
});

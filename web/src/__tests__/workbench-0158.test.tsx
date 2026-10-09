/**
 * 0.1.58 §2–§3: files Arslan writes show as cards and open in the reader; the reader shows
 * each kind of file the way it is read (HTML only sandboxed); paths in replies open the reader
 * or reveal in Finder; one workbench with 任务 / 文件 / 浏览器.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, apiMock } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), table: vi.fn(), html: vi.fn(), pdfPage: vi.fn(), open: vi.fn(),
    reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn() },
  apiMock: { downloadRunArtifact: vi.fn(), extractAttachmentFile: vi.fn(), updateSettings: vi.fn() },
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), api: apiMock }));
vi.mock("../api/tasks", () => ({ backgroundJobsApi: { list: vi.fn().mockResolvedValue({ jobs: [] }), stop: vi.fn() } }));
vi.mock("../components/BrowserReader", () => ({ default: () => <div data-testid="browser-reader" /> }));

import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useWorkbench } from "../stores/workbenchStore";
import { toUiMessages } from "../api/adapters";
import ReplyArtifacts from "../components/reply/ReplyArtifacts";
import Reader, { COMPOSER_INSERT_EVENT } from "../components/workbench/Reader";
import Workbench from "../components/workbench/Workbench";
import PathChip, { _resetPathCache, isLocalPath } from "../components/PathChip";
import { openArtifact } from "../lib/workDock";
import type { StoredArtifact } from "../api/client.types";

const art = (title: string, i = 1): StoredArtifact => ({ kind: "file", run_id: 9, filename: `run_9_${"a".repeat(15)}${i}_${title.split("/").pop()}`,
  title, bytes: 2048, sha256: "b".repeat(64), media_type: "text/plain", url: "" });
const blob = (text: string) => new Blob([text]);

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: false, tab: "task", reader: null, folder: null });
  _resetPathCache();
  files.home.mockResolvedValue({ path: "~/Arslan", project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
  globalThis.URL.revokeObjectURL = vi.fn();
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("files a reply wrote", () => {
  it("a written file reaches the reply (it used to be dropped) and survives a reload", () => {
    const store = useArslanStore.getState();
    store.handleFrame({ type: "stream_start", source: "arslan", run_id: 9 } as never);
    store.handleFrame({ type: "tool_call", tool: "write_file", args_summary: '{"path": "报告/a.md"}' } as never);
    store.handleFrame({ type: "tool_result", tool: "write_file", ok: true, summary: "ok", artifact: art("报告/a.md") } as never);
    store.handleFrame({ type: "stream_chunk", content: "done" } as never);
    store.handleFrame({ type: "stream_end", message_id: 5, run_id: 9 } as never);
    expect(toUiMessages(useArslanStore.getState().items).find((m) => m.text === "done")?.files?.map((f) => f.title)).toEqual(["报告/a.md"]);
    useArslanStore.setState(initialArslanState(), true);
    useArslanStore.getState().handleFrame({ type: "history", messages: [
      { message_id: 5, role: "arslan", content: "done", spawn_id: null, run_id: 9, files: [art("报告/a.md")] }] } as never);
    expect(toUiMessages(useArslanStore.getState().items)[0].files?.map((f) => f.title)).toEqual(["报告/a.md"]);
  });

  it("shows up to three cards, one per path; the rest open the workbench; a card opens the reader", () => {
    render(<ReplyArtifacts files={[art("r/a.md", 1), art("r/b.csv", 2), art("r/c.pdf", 3), art("r/d.png", 4)]} />);
    expect(screen.getAllByTestId("file-card")).toHaveLength(3);
    fireEvent.click(screen.getByTestId("reply-more-files"));
    expect(useWorkbench.getState()).toMatchObject({ open: true, tab: "task" });
    fireEvent.click(screen.getByTestId("file-card-open-a.md"));
    expect(useWorkbench.getState().reader).toMatchObject({ kind: "artifact", file: { title: "r/a.md" } });
  });
});

describe("the reader", () => {
  const path = (p: string) => ({ kind: "path" as const, path: p });

  it("renders Markdown, with its source a click away", async () => {
    files.read.mockResolvedValue(blob("# Week 41\n\nDone."));
    render(<Reader source={path("~/Arslan/w.md")} onBack={() => {}} />);
    expect(await screen.findByTestId("reader-markdown")).toHaveTextContent("Week 41");
    fireEvent.click(screen.getByTestId("reader-mode-source"));
    expect(screen.getByTestId("reader-text")).toHaveTextContent("# Week 41");
  });

  it("draws HTML only in a sandbox with no permissions", async () => {
    files.read.mockResolvedValue(blob("<h1>Hi</h1><script>alert(1)</script>"));
    render(<Reader source={path("~/Arslan/p.html")} onBack={() => {}} />);
    const frame = await screen.findByTestId("reader-html");
    expect(frame.getAttribute("sandbox")).toBe("");
  });

  it("shows csv as a table and text with line numbers", async () => {
    files.read.mockResolvedValueOnce(blob('name,amount\n"Spruce, Ltd",12\n'));
    const { unmount } = render(<Reader source={path("~/Arslan/t.csv")} onBack={() => {}} />);
    const table = await screen.findByTestId("reader-table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(table).toHaveTextContent("Spruce, Ltd");
    unmount();
    files.read.mockResolvedValueOnce(blob("one\ntwo"));
    render(<Reader source={path("~/Arslan/n.txt")} onBack={() => {}} />);
    expect(await screen.findByTestId("reader-text")).toHaveTextContent("1one2two");
  });

  it("xlsx and Word read through the server; a PDF can fall back to page images", async () => {
    files.table.mockResolvedValue({ sheets: [{ name: "S", rows: [["a"]], truncated: false }] });
    const a = render(<Reader source={path("~/Arslan/x.xlsx")} onBack={() => {}} />);
    await screen.findByTestId("reader-table");
    a.unmount();
    files.html.mockResolvedValue({ html: "<p>doc</p>" });
    const b = render(<Reader source={path("~/Arslan/x.docx")} onBack={() => {}} />);
    expect((await screen.findByTestId("reader-doc")).getAttribute("sandbox")).toBe("");
    b.unmount();
    files.read.mockResolvedValue(blob("%PDF"));
    files.pdfPage.mockResolvedValue({ image: new Blob(["png"]), pages: 1 });
    render(<Reader source={path("~/Arslan/x.pdf")} onBack={() => {}} />);
    await screen.findByTestId("reader-pdf");
    fireEvent.click(screen.getByTestId("reader-pdf-as-images"));
    await screen.findByTestId("reader-pdf-images");
    expect(files.pdfPage).toHaveBeenCalledWith("~/Arslan/x.pdf", 0);
  });

  it("says why it cannot read, and puts a path into the conversation on request", async () => {
    files.read.mockRejectedValue({ status: 403, detail: { code: "outside" } });
    render(<Reader source={path("/etc/hosts.txt")} onBack={() => {}} />);
    expect(await screen.findByTestId("reader-error")).toHaveTextContent("workbench.outside");
    const got: string[] = [];
    window.addEventListener(COMPOSER_INSERT_EVENT, (e) => got.push((e as CustomEvent).detail), { once: true });
    fireEvent.click(screen.getByTestId("reader-add"));
    expect(got).toEqual(["`/etc/hosts.txt`"]);
  });
});

describe("paths in a reply", () => {
  it("recognises local paths only", () => {
    expect(isLocalPath("~/Arslan/报告/a.md")).toBe(true);
    expect(isLocalPath("/Users/x/a.pdf")).toBe(true);
    expect(isLocalPath("//cdn.example/x.js")).toBe(false);
    expect(isLocalPath("https://example.com/a")).toBe(false);
    expect(isLocalPath("a.md")).toBe(false);
  });

  it("readable opens the reader, elsewhere reveals in Finder, missing stays text — one stat per batch", async () => {
    files.stat.mockResolvedValue({ items: [
      { path: "~/Arslan/a.md", exists: true, readable: true, is_dir: false },
      { path: "/Library/x.txt", exists: true, readable: false, is_dir: false },
      { path: "~/gone.md", exists: false, readable: false, is_dir: false }] });
    render(<p><PathChip path="~/Arslan/a.md" /> <PathChip path="/Library/x.txt" /> <PathChip path="~/gone.md" fallback={<code>~/gone.md</code>} /></p>);
    const chips = await screen.findAllByTestId("path-chip");
    expect(files.stat).toHaveBeenCalledTimes(1);
    expect(chips).toHaveLength(2);
    fireEvent.click(chips[0]);
    expect(useWorkbench.getState().reader).toEqual({ kind: "path", path: "~/Arslan/a.md" });
    fireEvent.click(chips[1]);
    expect(files.reveal).toHaveBeenCalledWith("/Library/x.txt");
    expect(screen.getByText("~/gone.md").tagName).toBe("CODE");
  });
});

describe("the workbench", () => {
  it("one panel: 任务 / 文件 / 浏览器, files of THIS conversation, the reader over the tabs", async () => {
    files.conversationFiles.mockResolvedValue({ files: [{ ...art("报告/a.md"), created_at: "2026-10-09T08:00:00" }] });
    files.list.mockResolvedValue({ path: "~/Arslan", root: "~/Arslan", crumbs: [{ name: "Arslan", path: "~/Arslan" }], total: 2, more: false,
      entries: [{ name: "报告", path: "~/Arslan/报告", is_dir: true, bytes: null, modified: "2026-10-09T08:00:00" },
                { name: "a.md", path: "~/Arslan/报告/a.md", is_dir: false, bytes: 10, modified: "2026-10-09T08:00:00" }] });
    useWorkbench.getState().show("task");
    render(<Workbench conversationId="c1" taskId={null} temporary={false} />);
    expect(await screen.findByTestId("task-files")).toHaveTextContent("a.md");
    expect(files.conversationFiles).toHaveBeenCalledWith("c1");
    fireEvent.click(screen.getByTestId("workbench-tab-files"));
    const row = await screen.findByTestId("files-row-a.md");
    expect(row.querySelector("[data-touched]")).not.toBeNull();          // this conversation made it
    fireEvent.click(within(screen.getByTestId("files-row-报告")).getAllByRole("button")[0]);
    expect(useWorkbench.getState().folder).toBe("~/Arslan/报告");
    files.read.mockResolvedValue(blob("# A"));
    act(() => { openArtifact(art("报告/a.md")); });                   // a card or "preview" anywhere
    expect(await screen.findByTestId("reader")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("reader-back"));
    expect(screen.queryByTestId("reader")).toBeNull();
    fireEvent.click(screen.getByTestId("workbench-tab-browser"));
    expect(screen.getByTestId("dock-embedded")).toBeInTheDocument();
  });

  it("⋯ holds keep-awake and close", async () => {
    apiMock.updateSettings.mockResolvedValue({ keep_awake_enabled: false });
    useWorkbench.getState().show("task");
    render(<Workbench conversationId="c1" taskId={null} temporary={false} />);
    fireEvent.click(screen.getByTestId("workbench-more"));
    fireEvent.click(screen.getByTestId("workbench-keep-awake"));
    await waitFor(() => expect(apiMock.updateSettings).toHaveBeenCalledWith({ keep_awake_enabled: false }));
  });
});

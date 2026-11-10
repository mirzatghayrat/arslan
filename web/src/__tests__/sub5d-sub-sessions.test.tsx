/**
 * SUB5d (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md, the approved mock): the Mac's window shows sub-sessions
 * as a tree under the conversation that started them.
 *
 * - The sidebar nests them under their commander (deeper levels the same way), never in a list of their own; a tree
 *   with a running or waiting sub-session starts open, a finished one closed; the arrow folds and unfolds it.
 * - Each sub-session's status is an icon, not a word: the word is its label; with reduced motion nothing moves.
 * - Opening a sub-session opens its tree down to it.
 * - Dragging a commander onto a project moves it (its tree reads its project); a sub-session can't be dragged out.
 * - Inside a sub-session: whose it is, with the way back. Inside a commander: its sub-sessions and the tree's spend.
 * - Deleting a commander: "also delete its N sub-sessions" (every level), ticked by default; each choice sends its
 *   query; the server's 409 and 422 are shown; while one runs there is no delete.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) => (o ? `${k} ${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" },
  }),
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

import { deleteConversation } from "../api/client";
import Sidebar from "../components/Sidebar";
import SubDeleteDialog from "../components/SubDeleteDialog";
import SubSessionBar from "../components/SubSessionBar";
import SubStatusIcon from "../components/SubStatusIcon";
import { metaFrom, type ConversationMeta } from "../lib/conversationMeta";
import { buildForest, descendants, startsOpen, treeOrder } from "../lib/subTree";
import { useRecency } from "../stores/recencyStore";
import { useSidebar } from "../stores/sidebarStore";

const NOW = new Date(2026, 10, 9, 15, 0);
const meta = (hoursAgo: number, extra: Partial<ConversationMeta> = {}): ConversationMeta =>
  ({ kind: "chat", state: "idle", origin: "mac", files: 0, lastAt: new Date(NOW.getTime() - hoursAgo * 3_600_000).toISOString(), ...extra });
const baseProps = {
  activeThreadId: "", onSelectThread: () => {}, onAddThread: () => {}, activeSection: "arslan" as const,
  onChangeSection: () => {}, onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
  backendStatus: "online" as const,
};
// "cmd" started "s1" and "s2"; "s1" started "s1a". "done" started "d1", which has finished. "plain" started nothing.
const threads = ["cmd", "s1", "s2", "s1a", "done", "d1", "plain"].map((id) => ({ id, title: `T-${id}` }));
const tree = (states: Partial<Record<string, ConversationMeta["state"]>> = {}): Record<string, ConversationMeta> => ({
  cmd: meta(1), s1: meta(1, { parentId: "cmd", kind: "task", state: states.s1 ?? "working" }),
  s2: meta(2, { parentId: "cmd", kind: "task", state: states.s2 ?? "done" }),
  s1a: meta(1, { parentId: "s1", kind: "task", state: states.s1a ?? "done" }),
  done: meta(3), d1: meta(3, { parentId: "done", kind: "task", state: "done" }), plain: meta(4),
});
const row = (id: string) => document.getElementById(`active-thread-btn-${id}`);
const shown = () => Array.from(document.querySelectorAll('[id^="active-thread-btn-"]')).map((el) => el.id.replace("active-thread-btn-", ""));

function reducedMotion(on: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: on && query.includes("reduce"), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), onchange: null, dispatchEvent: vi.fn(),
  }));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  useRecency.setState({ touched: {} });
  useSidebar.setState({ collapsed: false, pins: {} });
  try { localStorage.clear(); } catch { /* storage off */ }
  reducedMotion(false);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("the tree (lib/subTree)", () => {
  it("is built from the server's parent_id, every level, and a sub-session whose parent is not listed stands alone", () => {
    const rows = metaFrom([
      { conversation_id: "cmd", title: "", message_count: 1 },
      { conversation_id: "s1", title: "", message_count: 1, parent_id: "cmd" },
      { conversation_id: "s1a", title: "", message_count: 1, parent_id: "s1" },
      { conversation_id: "kept", title: "", message_count: 1, parent_id: "gone" },
    ]);
    const forest = buildForest(Object.keys(rows), rows);
    expect(forest.children).toEqual({ cmd: ["s1"], s1: ["s1a"] });
    expect(descendants("cmd", forest)).toEqual(["s1", "s1a"]);
    expect("kept" in forest.parentOf).toBe(false);
  });

  it("starts open while something under it runs or waits on you, closed when all is done", () => {
    const forest = buildForest(threads.map((t) => t.id), tree());
    expect(startsOpen("cmd", forest, tree())).toBe(true);                                       // s1 runs
    expect(startsOpen("cmd", forest, tree({ s1: "done", s1a: "waiting" }))).toBe(true);          // a grandchild waits
    expect(startsOpen("cmd", forest, tree({ s1: "done" }))).toBe(false);
    expect(startsOpen("done", forest, tree())).toBe(false);
  });

  it("orders a project's list as trees, each commander followed by its sub-sessions", () => {
    const rows = [{ conversation_id: "s1a", parent_id: "s1" }, { conversation_id: "x" }, { conversation_id: "s1", parent_id: "cmd" },
      { conversation_id: "cmd", parent_id: null }];
    expect(treeOrder(rows).map(({ row, depth }) => [row.conversation_id, depth])).toEqual([["x", 0], ["cmd", 0], ["s1", 1], ["s1a", 2]]);
  });
});

describe("the sidebar", () => {
  it("nests sub-sessions under their commander, never in a list of their own, and shows how many it started", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={tree()} />);
    // cmd's tree runs (s1), so it is open; s1's own tree (s1a) and "done" have finished, so they are closed.
    expect(shown()).toEqual(["cmd", "s1", "s2", "done", "plain"]);
    fireEvent.click(screen.getByTestId("sub-toggle-s1"));
    expect(shown()).toEqual(["cmd", "s1", "s1a", "s2", "done", "plain"]);
    expect(row("s1")).toHaveAttribute("data-depth", "1");
    expect(row("s1a")).toHaveAttribute("data-depth", "2");
    expect(row("cmd")).not.toHaveAttribute("data-depth");
    expect(screen.getByTestId("sub-toggle-cmd")).toHaveTextContent("2");
    expect(screen.getByTestId("sub-toggle-cmd")).toHaveAttribute("aria-label", 'subTree.toggle {"count":3}');   // every level
    expect(screen.getByTestId("sub-toggle-cmd")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("sub-toggle-done")).toHaveAttribute("aria-expanded", "false");
    expect(within(screen.getByTestId("sub-tree-cmd")).queryByText("T-plain")).toBeNull();
  });

  it("folds and unfolds a tree with its arrow, without opening the conversation", () => {
    const onSelectThread = vi.fn();
    render(<Sidebar {...baseProps} threads={threads} meta={tree()} onSelectThread={onSelectThread} />);
    fireEvent.click(screen.getByTestId("sub-toggle-cmd"));
    expect(shown()).toEqual(["cmd", "done", "plain"]);
    fireEvent.click(screen.getByTestId("sub-toggle-done"));
    expect(shown()).toEqual(["cmd", "done", "d1", "plain"]);
    expect(onSelectThread).not.toHaveBeenCalled();
  });

  it("shows each sub-session's status as an icon whose label is the word", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={tree({ s2: "waiting" })} />);
    fireEvent.click(screen.getByTestId("sub-toggle-s1"));
    expect(within(row("s1")!).getByRole("img", { name: "subTree.status.running" })).toBeInTheDocument();
    expect(within(row("s2")!).getByRole("img", { name: "subTree.status.waiting" })).toBeInTheDocument();
    expect(within(row("s1a")!).getByRole("img", { name: "subTree.status.done" })).toBeInTheDocument();
    expect(within(row("cmd")!).queryByRole("img", { name: /subTree\.status/ })).toBeNull();      // a commander has its glyph
  });

  it("opens a finished tree down to a sub-session when that one is opened", () => {
    const finished = tree({ s1: "done" });
    const { rerender } = render(<Sidebar {...baseProps} threads={threads} meta={finished} activeThreadId="plain" />);
    expect(shown()).not.toContain("s1a");
    rerender(<Sidebar {...baseProps} threads={threads} meta={finished} activeThreadId="s1a" />);
    expect(shown()).toEqual(["cmd", "s1", "s1a", "s2", "done", "plain"]);
  });

  it("moves a commander's whole tree when it is dragged onto a project, and a sub-session can't be dragged out", () => {
    const onMoveToProject = vi.fn();
    const data: Record<string, string> = {};
    const dataTransfer = { setData: (k: string, v: string) => { data[k] = v; }, getData: (k: string) => data[k] ?? "",
      get types() { return Object.keys(data); }, effectAllowed: "", dropEffect: "" };
    const { rerender } = render(<Sidebar {...baseProps} threads={threads} meta={tree()} projects={[{ id: "proj", name: "Proj" }]}
      onMoveToProject={onMoveToProject} />);
    expect(row("s1")).not.toHaveAttribute("draggable");
    expect(row("cmd")).toHaveAttribute("draggable", "true");
    fireEvent.dragStart(row("cmd")!, { dataTransfer });
    fireEvent.drop(screen.getByTestId("sidebar-project-drop-proj"), { dataTransfer });
    expect(onMoveToProject).toHaveBeenCalledWith("cmd", "proj");
    expect(onMoveToProject).toHaveBeenCalledTimes(1);
    // The server moves the tree (a sub-session reads its commander's project); in the project, the tree comes with it.
    rerender(<Sidebar {...baseProps} threads={threads} meta={{ ...tree(), cmd: meta(1, { projectId: "proj" }) }}
      projects={[{ id: "proj", name: "Proj" }]} onMoveToProject={onMoveToProject} />);
    fireEvent.click(screen.getByTestId("sidebar-project-toggle-proj"));
    const project = screen.getByTestId("sidebar-project-proj");
    expect(Array.from(project.querySelectorAll('[id^="active-thread-btn-"]')).map((el) => el.id)).toEqual(
      ["active-thread-btn-cmd", "active-thread-btn-s1", "active-thread-btn-s2"]);
    expect(shown().filter((id) => id === "s1")).toHaveLength(1);                     // not also under a date section
  });
});

describe("a sub-session that ended without finishing", () => {
  // As the server's list sends them: a stop reads "failed" with outcome "stopped"; a restart and a job that didn't get there
  // both read "unfinished", told apart by `outcome`.
  const rows = metaFrom([
    { conversation_id: "cmd", title: "", message_count: 1 },
    { conversation_id: "stopped", title: "", message_count: 1, parent_id: "cmd", state: "failed", outcome: "stopped" },
    { conversation_id: "failed", title: "", message_count: 1, parent_id: "cmd", state: "unfinished", outcome: "partial" },
    { conversation_id: "interrupted", title: "", message_count: 1, parent_id: "cmd", state: "unfinished", outcome: "interrupted" },
    { conversation_id: "finished", title: "", message_count: 1, parent_id: "cmd", state: "done_unseen", outcome: "done" },
  ]);
  const kids = ["cmd", "stopped", "failed", "interrupted", "finished"].map((id) => ({ id, title: `T-${id}` }));

  it("shows a still grey hollow ring labelled with what happened; only a finished one shows the check", () => {
    render(<Sidebar {...baseProps} threads={kids} meta={rows} />);
    fireEvent.click(screen.getByTestId("sub-toggle-cmd"));                     // nothing runs, so the tree starts closed
    for (const id of ["stopped", "failed", "interrupted"]) {
      const icon = within(row(id)!).getByRole("img", { name: `subTree.status.${id}` });
      expect(icon).toHaveAttribute("title", `subTree.status.${id}`);
      expect(icon).toHaveAttribute("data-look", "hollow-ring");
      expect(icon.querySelector(".animate-spin, .animate-pulse")).toBeNull();
    }
    const done = within(row("finished")!).getByRole("img", { name: "subTree.status.done" });
    expect(done).toHaveAttribute("data-look", "check");
  });

  it("one that finished but is still reporting reads at work: a running ring labelled reporting, and the tree is busy", () => {
    const reporting = metaFrom([
      { conversation_id: "cmd", title: "", message_count: 1 },
      { conversation_id: "rep", title: "", message_count: 1, parent_id: "cmd", state: "working", reporting: true },
    ]);
    render(<Sidebar {...baseProps} threads={[{ id: "cmd", title: "c" }, { id: "rep", title: "r" }]} meta={reporting} />);
    const icon = within(row("rep")!).getByRole("img", { name: "subTree.status.reporting" });
    expect(icon).toHaveAttribute("data-look", "spinning-ring");
    expect(startsOpen("cmd", buildForest(["cmd", "rep"], reporting), reporting)).toBe(true);
  });

  it("is not at work: its tree starts closed and can be deleted", () => {
    const forest = buildForest(Object.keys(rows), rows);
    expect(startsOpen("cmd", forest, rows)).toBe(false);
  });
});

describe("the status icon", () => {
  it("moves while running or waiting, and stays still with reduced motion asked for", () => {
    const { rerender } = render(<SubStatusIcon status="running" />);
    expect(screen.getByRole("img", { name: "subTree.status.running" })).toHaveAttribute("data-motion", "moving");
    expect(screen.getByRole("img").querySelector(".animate-spin")).not.toBeNull();
    rerender(<SubStatusIcon status="waiting" />);
    expect(screen.getByRole("img").querySelector(".animate-pulse")).not.toBeNull();
    cleanup();
    reducedMotion(true);
    for (const status of ["running", "waiting", "done"] as const) {
      render(<SubStatusIcon status={status} />);
      const icon = screen.getByRole("img", { name: `subTree.status.${status}` });
      expect(icon).toHaveAttribute("title", `subTree.status.${status}`);
      expect(icon).toHaveAttribute("data-motion", "still");
      expect(icon.querySelector(".animate-spin, .animate-pulse")).toBeNull();
      cleanup();
    }
  });
});

function fetchAnswers(...answers: { status: number; body: unknown }[]) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET" });
    const next = answers.shift() ?? { status: 200, body: { ok: true } };
    return new Response(JSON.stringify(next.body), { status: next.status, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

describe("the delete dialog", () => {
  const target = { id: "cmd", title: "T-cmd", count: 3, running: false };

  it("offers to delete every level of sub-sessions, ticked by default, and sends delete", async () => {
    const calls = fetchAnswers({ status: 200, body: { ok: true, deleted: {} } });
    const onDeleted = vi.fn();
    render(<SubDeleteDialog target={target} onClose={() => {}} onDeleted={onDeleted} />);
    expect(screen.getByText(/subTree\.delete\.also/)).toHaveTextContent('"count":3');
    expect(screen.getByTestId("sub-delete-also")).toBeChecked();
    await act(async () => { fireEvent.click(screen.getByTestId("sub-delete-confirm")); });
    expect(calls).toEqual([{ url: expect.stringMatching(/\/conversations\/cmd\?sub_sessions=delete$/), method: "DELETE" }]);
    expect(onDeleted).toHaveBeenCalledWith("cmd", "delete");
  });

  it("unticked, deletes only the commander and keeps its sub-sessions", async () => {
    const calls = fetchAnswers({ status: 200, body: { ok: true, deleted: {}, kept: ["s1", "s2"] } });
    const onDeleted = vi.fn();
    render(<SubDeleteDialog target={target} onClose={() => {}} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByTestId("sub-delete-also"));
    expect(screen.getByTestId("sub-delete-keep-note")).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByTestId("sub-delete-confirm")); });
    expect(calls[0].url).toMatch(/\/conversations\/cmd\?sub_sessions=keep$/);
    expect(onDeleted).toHaveBeenCalledWith("cmd", "keep");
  });

  it("while one runs, says to stop it first and offers no delete", () => {
    const calls = fetchAnswers();
    render(<SubDeleteDialog target={{ ...target, running: true }} onClose={() => {}} onDeleted={vi.fn()} />);
    expect(screen.getByTestId("sub-delete-running")).toHaveTextContent("subTree.delete.stopFirst");
    expect(screen.queryByTestId("sub-delete-confirm")).toBeNull();
    expect(screen.queryByTestId("sub-delete-also")).toBeNull();
    expect(calls).toEqual([]);
  });

  it("shows the server's 409 (one started running) and takes the delete away", async () => {
    fetchAnswers({ status: 409, body: { detail: { code: "sub_sessions_running" } } });
    const onDeleted = vi.fn();
    render(<SubDeleteDialog target={target} onClose={() => {}} onDeleted={onDeleted} />);
    await act(async () => { fireEvent.click(screen.getByTestId("sub-delete-confirm")); });
    await waitFor(() => expect(screen.getByTestId("sub-delete-running")).toBeInTheDocument());
    expect(screen.queryByTestId("sub-delete-confirm")).toBeNull();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("deletes a sub-session as one, and an ordinary conversation as before", async () => {
    const calls = fetchAnswers();
    await deleteConversation("s1", { subSession: true });
    await deleteConversation("plain");
    expect(calls.map((call) => call.url.replace(/^.*\/api\/v1/, ""))).toEqual(["/conversations/s1?sub_session=true", "/conversations/plain"]);
  });

  it("shows the server's 422 with its count", async () => {
    fetchAnswers({ status: 422, body: { detail: { code: "sub_sessions_choice_required", sub_sessions: 4 } } });
    const onDeleted = vi.fn();
    render(<SubDeleteDialog target={target} onClose={() => {}} onDeleted={onDeleted} />);
    await act(async () => { fireEvent.click(screen.getByTestId("sub-delete-confirm")); });
    await waitFor(() => expect(screen.getByTestId("sub-delete-error")).toHaveTextContent('subTree.delete.choiceRequired {"count":4}'));
    expect(onDeleted).not.toHaveBeenCalled();
  });
});

describe("inside a conversation", () => {
  it("in a sub-session: whose it is, and the way back", () => {
    const onOpen = vi.fn();
    render(<SubSessionBar conversationId="s1a" threads={threads} meta={tree()} usdCap={2} usdCapEnabled onOpen={onOpen} />);
    expect(screen.getByTestId("sub-session-header")).toHaveTextContent('subTree.header {"name":"T-s1"}');
    fireEvent.click(screen.getByTestId("sub-session-back"));
    expect(onOpen).toHaveBeenCalledWith("s1");
    expect(screen.queryByTestId("sub-session-panel")).toBeNull();
  });

  it("in a commander: each sub-session with its status and Open, and the tree's spend against its limit", async () => {
    const calls = fetchAnswers({ status: 200, body: { spent_usd: 1.5 } });
    const onOpen = vi.fn();
    render(<SubSessionBar conversationId="cmd" threads={threads} meta={tree()} usdCap={2} usdCapEnabled onOpen={onOpen} />);
    const panel = screen.getByTestId("sub-session-panel");
    expect(within(screen.getByTestId("sub-session-item-s1")).getByRole("img", { name: "subTree.status.running" })).toBeInTheDocument();
    expect(within(panel).getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(within(screen.getByTestId("sub-session-item-s2")).getByRole("button", { name: "subTree.open" }));
    expect(onOpen).toHaveBeenCalledWith("s2");
    await waitFor(() => expect(screen.getByTestId("sub-session-spend")).toHaveTextContent(
      'subTree.spend {"spent":"$1.50","limit":"$6.00","each":"$2.00","times":3}'));
    expect(calls[0].url).toMatch(/\/conversations\/cmd\/sub-sessions\/spend$/);
  });

  it("says there is no dollar limit when the user turned it off", async () => {
    fetchAnswers({ status: 200, body: { spent_usd: 0.25 } });
    render(<SubSessionBar conversationId="cmd" threads={threads} meta={tree()} usdCap={2} usdCapEnabled={false} onOpen={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId("sub-session-spend")).toHaveTextContent('subTree.spendNoLimit {"spent":"$0.25"}'));
  });

  it("shows nothing in a conversation that is in no tree", () => {
    render(<SubSessionBar conversationId="plain" threads={threads} meta={tree()} usdCap={2} usdCapEnabled onOpen={vi.fn()} />);
    expect(screen.queryByTestId("sub-session-bar")).toBeNull();
  });
});

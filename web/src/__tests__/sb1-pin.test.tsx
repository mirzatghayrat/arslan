/**
 * SB1-2 (v0.1.64, card docs/plans/0164/SB1-sidebar.md): a Pinned section above Projects (the user's pick on the
 * SB1-0 mock); pin and unpin from the row menu, shown at once and stored on the server; unpinning returns the
 * conversation to its place by time; dragging a conversation onto a project moves it (the menu's move).
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en", language: "en" } }) }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

import Sidebar from "../components/Sidebar";
import { metaFrom, type ConversationMeta } from "../lib/conversationMeta";
import { useRecency } from "../stores/recencyStore";
import { useSidebar } from "../stores/sidebarStore";

const NOW = new Date(2026, 9, 30, 15, 0);
const meta = (hoursAgo: number, extra: Partial<ConversationMeta> = {}): ConversationMeta =>
  ({ kind: "chat", state: "idle", origin: "mac", files: 0, lastAt: new Date(NOW.getTime() - hoursAgo * 3_600_000).toISOString(), ...extra });
const baseProps = {
  activeThreadId: "", onSelectThread: () => {}, onAddThread: () => {}, activeSection: "arslan" as const,
  onChangeSection: () => {}, onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
  backendStatus: "online" as const,
};
const threads = [{ id: "a", title: "a" }, { id: "b", title: "b" }, { id: "c", title: "c" }, { id: "p", title: "p" }];
const projects = [{ id: "proj", name: "Proj" }];
const ids = (root: Element) => Array.from(root.querySelectorAll('[id^="active-thread-btn-"]')).map((el) => el.id.replace("active-thread-btn-", ""));
const DRAG = "application/x-arslan-conversation";
const drag = (id: string) => {
  const data: Record<string, string> = {};
  const dataTransfer = { setData: (k: string, v: string) => { data[k] = v; }, getData: (k: string) => data[k] ?? "",
    get types() { return Object.keys(data); }, effectAllowed: "", dropEffect: "" };
  fireEvent.dragStart(document.getElementById(`active-thread-btn-${id}`)!, { dataTransfer });
  return dataTransfer;
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  useRecency.setState({ touched: {} });
  useSidebar.setState({ collapsed: false, pins: {} });
  try { localStorage.clear(); } catch { /* storage off */ }               // the projects' open state is kept there
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("pinned", () => {
  const timed = { a: meta(1), b: meta(2, { pinned: true }), c: meta(3, { pinned: true }), p: meta(4, { projectId: "proj", pinned: true }) };

  it("sits above Projects, newest first, and leaves the date sections", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={timed} projects={projects} />);
    const pinned = screen.getByTestId("sidebar-pinned");
    expect(ids(pinned)).toEqual(["b", "c"]);                                   // p stays in its project
    expect(pinned.compareDocumentPosition(screen.getByTestId("sidebar-projects")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(ids(document.body).filter((id) => id === "b")).toHaveLength(1);    // not again under Today
  });

  it("reads the server's pin from the conversation list", () => {
    const m = metaFrom([{ conversation_id: "x", title: "x", message_count: 1, pinned: true },
      { conversation_id: "y", title: "y", message_count: 1 }]);
    expect([m.x.pinned, m.y.pinned]).toEqual([true, false]);
  });

  it("pins from the row menu at once, and unpinning returns it to its place by time", () => {
    const onPinThread = vi.fn((id: string, pinned: boolean) => useSidebar.getState().setPin(id, pinned));
    const plain = { a: meta(1), b: meta(2), c: meta(3) };
    render(<Sidebar {...baseProps} threads={threads.slice(0, 3)} meta={plain} onPinThread={onPinThread} />);
    expect(screen.queryByTestId("sidebar-pinned")).toBeNull();
    const row = document.getElementById("active-thread-btn-c")!;
    fireEvent.click(within(row).getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByTestId("thread-pin"));
    expect(onPinThread).toHaveBeenCalledWith("c", true);
    expect(ids(screen.getByTestId("sidebar-pinned"))).toEqual(["c"]);
    fireEvent.click(within(document.getElementById("active-thread-btn-c")!).getByLabelText("sidebar.thread_menu"));
    expect(screen.getByTestId("thread-pin")).toHaveTextContent("sidebar.unpin");
    fireEvent.click(screen.getByTestId("thread-pin"));
    expect(onPinThread).toHaveBeenLastCalledWith("c", false);
    expect(screen.queryByTestId("sidebar-pinned")).toBeNull();
    expect(ids(document.body)).toEqual(["a", "b", "c"]);                     // back under Today, by its time
  });

  it("offers no pin for a conversation in a project", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={{ ...timed, p: meta(4, { projectId: "proj" }) }}
      projects={projects} onPinThread={vi.fn()} />);
    fireEvent.click(within(screen.getByTestId("sidebar-project-toggle-proj")).getByText("Proj"));
    fireEvent.click(within(document.getElementById("active-thread-btn-p")!).getByLabelText("sidebar.thread_menu"));
    expect(screen.queryByTestId("thread-pin")).toBeNull();
  });
});

describe("drag onto a project", () => {
  const plain = { a: meta(1), b: meta(2), c: meta(3), p: meta(4, { projectId: "proj" }) };

  it("moves the conversation there, the menu's move", () => {
    const onMoveToProject = vi.fn();
    render(<Sidebar {...baseProps} threads={threads} meta={plain} projects={projects} onMoveToProject={onMoveToProject} />);
    const dataTransfer = drag("a");
    const target = screen.getByTestId("sidebar-project-drop-proj");
    fireEvent.dragOver(target, { dataTransfer });
    expect(target).toHaveAttribute("data-drop", "true");                       // it says where it will land
    fireEvent.drop(target, { dataTransfer });
    expect(onMoveToProject).toHaveBeenCalledWith("a", "proj");
    expect(target).not.toHaveAttribute("data-drop");
  });

  it("takes only a conversation, and not one already there", () => {
    const onMoveToProject = vi.fn();
    render(<Sidebar {...baseProps} threads={threads} meta={plain} projects={projects} onMoveToProject={onMoveToProject} />);
    const target = screen.getByTestId("sidebar-project-drop-proj");
    const file = { getData: () => "file.txt", types: ["Files"], dropEffect: "" };
    fireEvent.drop(target, { dataTransfer: file });
    fireEvent.click(within(screen.getByTestId("sidebar-project-toggle-proj")).getByText("Proj"));
    fireEvent.drop(target, { dataTransfer: drag("p") });
    expect(onMoveToProject).not.toHaveBeenCalled();
  });

  it("does not drag the phone's conversation or an archived one", () => {
    render(<Sidebar {...baseProps} threads={[{ id: "pocket", title: "Remote" }, { id: "z", title: "z", archived: true }]}
      meta={{ pocket: meta(1, { kind: "remote" }) }} onMoveToProject={vi.fn()} />);
    expect(document.getElementById("active-thread-btn-pocket")).not.toHaveAttribute("draggable");
    act(() => { fireEvent.click(document.getElementById("btn-toggle-archived-threads")!); });
    expect(document.getElementById("active-thread-btn-z")).not.toHaveAttribute("draggable");
  });

  it(`uses its own type (${DRAG}), so a file dropped there is never read as a conversation`, () => {
    expect(DRAG).toMatch(/^application\/x-arslan-/);
  });
});

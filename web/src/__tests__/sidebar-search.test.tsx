/**
 * The sidebar's search (v0.1.64, the approved mock):
 *
 * - ⌘K focuses the field at the top of the conversation list (⌘F does not); Esc clears it.
 * - Titles filter as you type, sub-sessions too; a sub-session says whose it is ("Under …").
 * - Opening a result opens it, and a sub-session's tree opens down to it.
 * - "In messages" lists the server's snippets as text, the match in a <mark>; an <img> in a snippet stays text.
 * - With nothing typed, the usual list; with nothing found, the mock's "nothing found" and what is never searched.
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

import { api, type ConversationHit } from "../api/client";
import Sidebar from "../components/Sidebar";
import type { ConversationMeta } from "../lib/conversationMeta";
import { useRecency } from "../stores/recencyStore";
import { useSidebar } from "../stores/sidebarStore";

const NOW = new Date(2026, 10, 9, 15, 0);
const meta = (hoursAgo: number, extra: Partial<ConversationMeta> = {}): ConversationMeta =>
  ({ kind: "chat", state: "idle", origin: "mac", files: 0, lastAt: new Date(NOW.getTime() - hoursAgo * 3_600_000).toISOString(), ...extra });
// "cmd" started "s1", which started "s1a"; all finished, so the tree starts closed. "plain" started nothing.
const threads = [
  { id: "cmd", title: "Sort the photo backup" }, { id: "s1", title: "Group photos by date" },
  { id: "s1a", title: "Compare photo hashes" }, { id: "plain", title: "Weekly report" },
];
const tree: Record<string, ConversationMeta> = {
  cmd: meta(1), s1: meta(1, { parentId: "cmd", kind: "task", state: "done" }),
  s1a: meta(1, { parentId: "s1", kind: "task", state: "done" }), plain: meta(2),
};
const props = {
  threads, meta: tree, activeThreadId: "", onSelectThread: vi.fn(), onAddThread: () => {}, activeSection: "arslan" as const,
  onChangeSection: () => {}, onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
  backendStatus: "online" as const,
};
const field = () => screen.getByTestId("sidebar-search") as HTMLInputElement;
const type = (value: string) => fireEvent.change(field(), { target: { value } });
const row = (id: string) => document.getElementById(`active-thread-btn-${id}`);
let search: ReturnType<typeof vi.spyOn>;
const answer = (hits: ConversationHit[]) => search.mockResolvedValue(hits);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  useRecency.setState({ touched: {} });
  useSidebar.setState({ collapsed: false, pins: {} });
  try { localStorage.clear(); } catch { /* storage off */ }
  search = vi.spyOn(api, "searchConversations");
  answer([]);
  props.onSelectThread.mockReset();
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("the field", () => {
  it("is focused by ⌘K, not by ⌘F, and shows the shortcut while empty", () => {
    render(<Sidebar {...props} />);
    expect(screen.getByText("⌘K")).toBeTruthy();
    fireEvent.keyDown(window, { key: "f", code: "KeyF", metaKey: true });
    expect(document.activeElement).not.toBe(field());
    fireEvent.keyDown(window, { key: "k", code: "KeyK", metaKey: true });
    expect(document.activeElement).toBe(field());
  });

  it("leaves Ctrl+K to the text field it's typed in (delete to the end of the line)", () => {
    render(<Sidebar {...props} />);
    const composer = document.createElement("textarea");
    document.body.appendChild(composer);
    composer.focus();
    const event = new KeyboardEvent("keydown", { key: "k", code: "KeyK", ctrlKey: true, bubbles: true, cancelable: true });
    composer.dispatchEvent(event);
    expect(document.activeElement).toBe(composer);
    expect(event.defaultPrevented).toBe(false);
    composer.remove();
  });

  it("⌘K shows a hidden sidebar and focuses the field", async () => {
    useSidebar.setState({ collapsed: true });
    render(<Sidebar {...props} />);
    expect(screen.queryByTestId("sidebar-search")).toBeNull();
    fireEvent.keyDown(window, { key: "k", code: "KeyK", metaKey: true });
    await waitFor(() => expect(document.activeElement).toBe(field()));
  });

  it("Esc clears it and the usual list comes back", () => {
    render(<Sidebar {...props} />);
    type("weekly");
    expect(row("plain")).toBeNull();
    expect(screen.getByTestId("search-title-plain")).toBeTruthy();
    fireEvent.keyDown(field(), { key: "Escape" });
    expect(field().value).toBe("");
    expect(screen.queryByTestId("sidebar-search-results")).toBeNull();
    expect(row("plain")).toBeTruthy();
    expect(screen.getByText("⌘K")).toBeTruthy();
  });

  it("with nothing typed, shows the usual list and asks the server nothing", () => {
    render(<Sidebar {...props} />);
    type("   ");
    expect(row("cmd")).toBeTruthy();
    expect(screen.queryByTestId("sidebar-search-results")).toBeNull();
    expect(screen.queryByTestId("sidebar-search-none")).toBeNull();
    expect(search).not.toHaveBeenCalled();
  });
});

describe("titles", () => {
  it("filter as you type, sub-sessions included, each saying whose it is", () => {
    render(<Sidebar {...props} />);
    type("PHOTO");
    const results = screen.getByTestId("sidebar-search-results");
    expect(within(results).getAllByRole("button").map(b => b.dataset.testid).filter(Boolean))
      .toEqual(["search-title-cmd", "search-title-s1", "search-title-s1a"]);
    expect(screen.getByTestId("search-title-s1").textContent).toContain('subTree.under {"title":"Sort the photo backup"}');
    expect(screen.getByTestId("search-title-s1a").textContent).toContain('subTree.under {"title":"Group photos by date"}');
    expect(screen.getByTestId("search-title-cmd").textContent).not.toContain("subTree.under");
    expect(screen.getByTestId("search-title-cmd").querySelector("mark")?.textContent).toBe("photo");
  });

  it("opening a sub-session opens it and its tree down to it, even after the tree was folded", () => {
    render(<Sidebar {...props} activeThreadId="s1a" />);
    expect(screen.getByTestId("sub-tree-cmd")).toBeTruthy();             // the open one's tree opens with it
    fireEvent.click(screen.getByTestId("sub-toggle-cmd"));
    expect(screen.queryByTestId("sub-tree-cmd")).toBeNull();
    type("hashes");
    fireEvent.click(screen.getByTestId("search-title-s1a"));
    expect(props.onSelectThread).toHaveBeenCalledWith("s1a");
    expect(field().value).toBe("");
    expect(screen.getByTestId("sub-tree-cmd")).toBeTruthy();
    expect(screen.getByTestId("sub-tree-s1")).toBeTruthy();
    expect(row("s1a")).toBeTruthy();
  });

  it("opening a sub-session that isn't open yet opens every level above it", () => {
    render(<Sidebar {...props} />);
    expect(screen.queryByTestId("sub-tree-cmd")).toBeNull();
    type("hashes");
    fireEvent.click(screen.getByTestId("search-title-s1a"));
    expect(props.onSelectThread).toHaveBeenCalledWith("s1a");
    expect(screen.getByTestId("sub-tree-cmd")).toBeTruthy();
    expect(screen.getByTestId("sub-tree-s1")).toBeTruthy();
  });
});

describe("in messages", () => {
  it("lists the server's snippets as text, the match marked; an <img> stays text", async () => {
    const snippet = 'see <img src=x onerror="window.__hit=1"> the report draft';
    answer([{ conversation_id: "plain", message_id: 7, who: "you", when: "2026-11-09 14:00", snippet },
      { conversation_id: "not-listed", message_id: 8, who: "you", when: null, snippet: "report elsewhere" }]);
    render(<Sidebar {...props} />);
    type("report");
    const hit = await screen.findByTestId("search-hit-7");
    expect(search).toHaveBeenCalledWith("report");
    expect(hit.querySelector("img")).toBeNull();
    expect(document.querySelector("img[src='x']")).toBeNull();
    const text = within(hit).getByTestId("search-snippet");
    expect(text.textContent).toBe(snippet);
    expect(Array.from(text.querySelectorAll("mark")).map(m => m.textContent)).toEqual(["report"]);
    expect(hit.textContent).toContain("Weekly report");
    expect(screen.queryByTestId("search-hit-8")).toBeNull();         // only what the sidebar lists
    expect(screen.getByText("sidebar.search.messages")).toBeTruthy();
    fireEvent.click(hit);
    expect(props.onSelectThread).toHaveBeenCalledWith("plain");
  });

  it("one character searches titles only", async () => {
    render(<Sidebar {...props} />);
    type("w");
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
    expect(search).not.toHaveBeenCalled();
    expect(screen.getByTestId("search-title-plain")).toBeTruthy();
  });
});

describe("nothing found", () => {
  it("says so, and that temporary and no-memory conversations are never searched", async () => {
    render(<Sidebar {...props} />);
    type("xyzzy");
    const none = await screen.findByTestId("sidebar-search-none");
    expect(search).toHaveBeenCalledWith("xyzzy");
    expect(none.textContent).toContain('sidebar.search.none {"query":"xyzzy"}');
    expect(none.textContent).toContain("sidebar.search.noneHint");
    expect(row("cmd")).toBeNull();
  });
});

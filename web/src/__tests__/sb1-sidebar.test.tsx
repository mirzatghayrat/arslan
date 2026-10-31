/**
 * SB1-1 (v0.1.64, card docs/plans/0164/SB1-sidebar.md): the sidebar keeps conversations newest first by
 * last activity and groups them as the iPhone does (Today / Yesterday / Previous 7 Days / Earlier by
 * month, calendar days); a message, a reply or a new conversation moves it to the top at once; it
 * collapses with a button or ⌃⌘S and remembers that.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en", language: "en" } }) }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

import Sidebar, { COLLAPSED_KEY, isToggleSidebarKey } from "../components/Sidebar";
import type { ConversationMeta } from "../lib/conversationMeta";
import { daysBack, groupByDay, newestFirst } from "../lib/sidebarOrder";
import { useRecency } from "../stores/recencyStore";
import { useSidebar } from "../stores/sidebarStore";

const NOW = new Date(2026, 9, 30, 15, 0);                     // 30 Oct 2026, 15:00 local
const at = (y: number, m: number, d: number, h = 12, min = 0) => new Date(y, m - 1, d, h, min);
const meta = (lastAt: Date | null): ConversationMeta =>
  ({ kind: "chat", state: "idle", origin: "mac", files: 0, lastAt: lastAt ? lastAt.toISOString() : null });
const baseProps = {
  activeThreadId: "", onSelectThread: () => {}, onAddThread: () => {}, activeSection: "arslan" as const,
  onChangeSection: () => {}, onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
  backendStatus: "online" as const,
};
const titles = () => Array.from(document.querySelectorAll('[id^="active-thread-btn-"]')).map((el) => el.id.replace("active-thread-btn-", ""));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  useRecency.setState({ touched: {} });
  try { localStorage.clear(); } catch { /* storage off */ }
  useSidebar.getState().reload();
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("the iPhone's sections (lib/sidebarOrder)", () => {
  it("counts calendar days, not 24-hour spans: one minute before midnight is yesterday", () => {
    expect(daysBack(at(2026, 10, 29, 23, 59), at(2026, 10, 30, 0, 1))).toBe(1);
    expect(daysBack(at(2026, 10, 30, 0, 0), at(2026, 10, 30, 23, 59))).toBe(0);
    expect(daysBack(at(2026, 10, 22, 23, 59), at(2026, 10, 30, 0, 1))).toBe(8);
    // Across a daylight-saving change (late March / late October in much of the world) a day is 23 or
    // 25 hours long; days are counted from the local calendar date, so the count is the same.
    expect(daysBack(at(2026, 3, 28, 1), at(2026, 3, 30, 1))).toBe(2);
    expect(daysBack(at(2026, 10, 24, 23), at(2026, 10, 26, 0))).toBe(2);
  });

  it("puts each age in its section: 0 Today, 1 Yesterday, 2–7 the 7 days, 8 and older by month", () => {
    const rows = [
      { id: "today", t: at(2026, 10, 30, 0, 5) }, { id: "none", t: null }, { id: "yest", t: at(2026, 10, 29, 23, 59) },
      { id: "d2", t: at(2026, 10, 28) }, { id: "d7", t: at(2026, 10, 23, 0, 1) }, { id: "d8", t: at(2026, 10, 22, 23, 59) },
      { id: "sep", t: at(2026, 9, 3) }, { id: "lastyear", t: at(2025, 9, 14) },
    ];
    const g = groupByDay(rows, (r) => r.t?.getTime() ?? null, NOW, "en");
    expect(g.today.map((r) => r.id)).toEqual(["none", "today"]);        // no time yet: newest
    expect(g.yesterday.map((r) => r.id)).toEqual(["yest"]);
    expect(g.week.map((r) => r.id)).toEqual(["d2", "d7"]);
    expect(g.months.map((m) => [m.id, m.title, m.rows.map((r) => r.id)])).toEqual([
      ["2026-10", "October", ["d8"]], ["2026-09", "September", ["sep"]], ["2025-09", "September 2025", ["lastyear"]]]);
  });

  it("keeps ties in their given order", () => {
    expect(newestFirst(["a", "b", "c"], () => 5)).toEqual(["a", "b", "c"]);
  });
});

describe("the sidebar", () => {
  const threads = [{ id: "old", title: "old" }, { id: "mid", title: "mid" }, { id: "new", title: "new" }];
  const timed: Record<string, ConversationMeta> = {
    old: meta(at(2026, 9, 2)), mid: meta(at(2026, 10, 29, 9)), new: meta(at(2026, 10, 30, 9)) };

  it("lists newest first under the iPhone's headings, with no time on the rows", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={timed} />);
    expect(screen.getByTestId("sidebar-section-today")).toHaveTextContent("sidebar.today");
    expect(screen.getByTestId("sidebar-section-yesterday")).toHaveTextContent("sidebar.yesterday");
    expect(screen.queryByTestId("sidebar-section-previous7")).toBeNull();      // empty sections are left out
    expect(screen.getByTestId("sidebar-section-earlier")).toBeInTheDocument();
    expect(titles()).toEqual(["new", "mid"]);                                  // "old" is folded in September
    expect(document.getElementById("active-thread-btn-new")?.textContent).not.toMatch(/\d{1,2}:\d{2}/);
  });

  it("opens a month with its count", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={timed} />);
    const month = screen.getByTestId("sidebar-month-2026-09");
    const toggle = within(month).getByRole("button");
    expect(toggle).toHaveTextContent("September1");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(titles()).toEqual(["new", "mid", "old"]);
  });

  it("opens the month that holds the open conversation", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={timed} activeThreadId="old" />);
    expect(within(screen.getByTestId("sidebar-month-2026-09")).getAllByRole("button")[0]).toHaveAttribute("aria-expanded", "true");
    expect(titles()).toContain("old");
  });

  it("moves a conversation to the top at once when this window sees activity in it", () => {
    render(<Sidebar {...baseProps} threads={threads} meta={timed} />);
    act(() => { useRecency.getState().touch("mid"); });                       // a message sent or a reply finished
    expect(titles()).toEqual(["mid", "new"]);
    act(() => { useRecency.getState().touch("old"); });                       // an old one comes back to Today
    expect(titles()).toEqual(["old", "mid", "new"]);
    expect(screen.queryByTestId("sidebar-section-earlier")).toBeNull();
  });

  it("puts a new conversation with no time yet at the top", () => {
    render(<Sidebar {...baseProps} threads={[...threads, { id: "fresh", title: "fresh" }]} meta={timed} />);
    expect(titles()[0]).toBe("fresh");
  });

  it("ranks project groups by their newest conversation, not by list order", () => {
    const projects = [{ id: "p1", name: "One" }, { id: "p2", name: "Two" }];
    const withProjects: Record<string, ConversationMeta> = {
      old: { ...timed.old, projectId: "p1" }, mid: timed.mid, new: { ...timed.new, projectId: "p2" } };
    render(<Sidebar {...baseProps} threads={threads} meta={withProjects} projects={projects} />);
    const order = Array.from(document.querySelectorAll('[data-testid^="sidebar-project-p"]'))
      .map((el) => el.getAttribute("data-testid")).filter((id) => /^sidebar-project-p\d$/.test(id ?? ""));
    expect(order).toEqual(["sidebar-project-p2", "sidebar-project-p1"]);
  });
});

describe("collapse", () => {
  it("collapses with the button and remembers it after a reload", () => {
    const { unmount } = render(<Sidebar {...baseProps} threads={[]} />);
    fireEvent.click(screen.getByTestId("sidebar-hide"));
    expect(screen.queryByRole("region", { name: "workspace.recentConversations" })).toBeNull();
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe("1");
    unmount();
    useSidebar.setState({ collapsed: false });                                 // a fresh window…
    useSidebar.getState().reload();                                            // …reads what was remembered
    render(<Sidebar {...baseProps} threads={[]} />);
    expect(screen.getByTestId("sidebar-show")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("sidebar-show"));
    expect(screen.getByRole("region", { name: "workspace.recentConversations" })).toBeInTheDocument();
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe("0");
  });

  it("toggles with ⌃⌘S and nothing else", () => {
    render(<Sidebar {...baseProps} threads={[]} />);
    fireEvent.keyDown(window, { key: "s", code: "KeyS", metaKey: true });              // ⌘S: not ours
    expect(screen.getByTestId("sidebar-hide")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "s", code: "KeyS", ctrlKey: true, metaKey: true });
    expect(screen.getByTestId("sidebar-show")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "s", code: "KeyS", ctrlKey: true, metaKey: true });
    expect(screen.getByTestId("sidebar-hide")).toBeInTheDocument();
    expect(isToggleSidebarKey(new KeyboardEvent("keydown", { key: "s", code: "KeyS", ctrlKey: true, metaKey: true, shiftKey: true }))).toBe(false);
  });
});

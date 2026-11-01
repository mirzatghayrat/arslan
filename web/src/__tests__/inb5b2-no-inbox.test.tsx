/** INB5b-2 (v0.1.64): the Inbox is gone (the INB5 board, approved 2026-10-31). What is waiting on you is one number on Progress in the
 *  sidebar, counted by the server (progress.waiting_on_user: conversations, projects and scheduled tasks, never rows); a clicked
 *  notice goes where its section says (the Scheduled page, useNotificationRoutes); and no "@inbox" route is left anywhere. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/companion/BackgroundJobs", () => ({ default: () => null }));
vi.mock("../api/proactive", () => ({ PROACTIVE_CHANGED: "arslan:proactive-changed", proactiveApi: { summary: vi.fn() } }));

import { proactiveApi } from "../api/proactive";
import Sidebar from "../components/Sidebar";
import { useNotificationRoutes } from "../hooks/useNotificationRoutes";
import { useWaiting } from "../hooks/useWaiting";
import { notificationTarget, OPEN_CONVERSATION_EVENT, PROGRESS_TARGET } from "../lib/openConversation";
import { SECTIONS } from "../lib/sections";
import de from "../locales/de.json";
import en from "../locales/en.json";
import es from "../locales/es.json";
import fr from "../locales/fr.json";
import ja from "../locales/ja.json";
import zh from "../locales/zh.json";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const props = (over: Partial<React.ComponentProps<typeof Sidebar>> = {}): React.ComponentProps<typeof Sidebar> => ({
  threads: [], activeThreadId: "", onSelectThread: vi.fn(), onAddThread: vi.fn(), activeSection: "arslan", onChangeSection: vi.fn(),
  onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(), backendStatus: "online", ...over,
});
const summary = (count: number) => ({ open: 0, unread: 0, high: 0, waiting: { count, conversations: [], projects: [], scheduled: [] } });

describe("the sidebar", () => {
  it("has no Inbox; Progress carries what is waiting on you, and opens", () => {
    const p = props({ waiting: 3 });
    render(<Sidebar {...p} />);
    expect(document.getElementById("nav-btn-inbox-deck")).toBeNull();
    expect(screen.getByTestId("progress-badge")).toHaveTextContent("3");
    fireEvent.click(document.getElementById("nav-btn-progress-footer")!);
    expect(p.onChangeSection).toHaveBeenCalledWith("progress");
  });

  it("shows no number when nothing waits, and caps a big one", () => {
    const { rerender } = render(<Sidebar {...props({ waiting: 0 })} />);
    expect(screen.queryByTestId("progress-badge")).toBeNull();
    rerender(<Sidebar {...props({ waiting: 120 })} />);
    expect(screen.getByTestId("progress-badge")).toHaveTextContent("99+");
  });

  it("reads 99 as 99 and 100 as 99+, in amber (#605 review F6)", () => {
    const { rerender } = render(<Sidebar {...props({ waiting: 99 })} />);
    expect(screen.getByTestId("progress-badge")).toHaveTextContent(/^99$/);
    expect(screen.getByTestId("progress-badge").className).toContain("bg-warning");
    rerender(<Sidebar {...props({ waiting: 100 })} />);
    expect(screen.getByTestId("progress-badge")).toHaveTextContent("99+");
  });

  it("marks the Archived fold while an archived conversation waits on you (#605 review F5)", () => {
    const threads = [{ id: "a", title: "A" }, { id: "b", title: "B", archived: true }, { id: "c", title: "C", archived: true }];
    const chat = (state: string) => ({ kind: "chat", state, origin: "mac", files: 0 });
    const { rerender } = render(<Sidebar {...props({ threads, meta: { b: chat("waiting"), c: chat("idle") } as never })} />);
    const fold = () => document.getElementById("btn-toggle-archived-threads")!;
    expect(within(fold()).getByRole("img", { name: "waiting.count" })).toBeTruthy();
    rerender(<Sidebar {...props({ threads, meta: { b: chat("idle"), c: chat("done_unseen") } as never })} />);
    expect(within(fold()).queryByRole("img")).toBeNull();
  });

  it("lists no inbox page", () => {
    expect(SECTIONS as readonly string[]).not.toContain("inbox");
  });
});

describe("the count", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });
  const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
  const changed = () => act(() => { window.dispatchEvent(new Event("arslan:proactive-changed")); });
  const answers = (value: unknown) => vi.mocked(proactiveApi.summary).mockImplementation(async () => {
    if (value instanceof Error) throw value;
    return value as never;
  });

  it("is the server's waiting count, refreshed when anything changes, and kept when a poll fails", async () => {
    answers(summary(2));
    const { result } = renderHook(() => useWaiting());
    await flush();
    expect(result.current.count).toBe(2);
    answers(summary(5));
    changed();
    await flush();
    expect(result.current.count).toBe(5);
    answers(new Error("restarting"));
    changed();
    await flush();
    expect(result.current.count).toBe(5);                                         // a restarting service does not zero it
  });

  it("clears when the server says nothing waits, after a failed poll too (#605 review F6)", async () => {
    answers(summary(2));
    const { result } = renderHook(() => useWaiting());
    await flush();
    answers(new Error("restarting"));
    changed();
    await flush();
    expect(result.current.count).toBe(2);
    answers(summary(0));
    changed();
    await flush();
    expect(result.current.count).toBe(0);
  });

  it("reads again a moment after a change, so a count read before the server applied it does not stand (#605 review F4)", async () => {
    answers(summary(1));
    const { result } = renderHook(() => useWaiting());
    await flush();
    changed();                                                                    // a card answered: the first read may still count it
    await flush();
    expect(result.current.count).toBe(1);
    answers(summary(0));                                                          // the server has applied it now
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(result.current.count).toBe(0);
  });
});

describe("Settings", () => {
  // Watched pages and folders, and what was muted, are managed on the Scheduled page (WatchesPanel, INB3), not in an Inbox that is gone.
  const INBOX: Record<string, string> = { en: "Inbox", zh: "收件箱", ja: "受信箱", de: "Posteingang", es: "Bandeja", fr: "boîte de réception" };
  it.each(Object.entries({ en, zh, ja, de, es, fr }))("points watches and mutes at the Scheduled page, not the Inbox, in %s", (language, words) => {
    const settings = words.settings as unknown as Record<string, string | undefined>;
    expect(settings.watchesOnScheduled, language).toContain(words.nav.scheduled);
    expect(settings.watchesOnScheduled, language).not.toContain(INBOX[language]);
    expect(settings.watchesInInbox, language).toBeUndefined();
    expect(settings.openInbox, language).toBeUndefined();
  });
});

describe("a clicked notice", () => {
  it("opens Progress, and the old Inbox route leads nowhere", () => {
    expect(PROGRESS_TARGET).toBe("@progress");
    expect(notificationTarget("@progress", [])).toEqual({ kind: "progress" });
    expect(notificationTarget("@inbox", [])).toBeNull();
  });

  it("opens the Scheduled page for now, where what was noticed is listed, and a conversation by its id (#605 review F1)", () => {
    const openSection = vi.fn();
    const selectConversation = vi.fn();
    renderHook(() => useNotificationRoutes({ threads: [{ id: "thread-1" }, { id: "thread-2", archived: true }], selectConversation, openSection }));
    const click = (id: string) => act(() => { window.dispatchEvent(new CustomEvent(OPEN_CONVERSATION_EVENT, { detail: id })); });
    click(PROGRESS_TARGET);
    expect(openSection).toHaveBeenCalledWith("scheduled");
    click("thread-1");
    expect(selectConversation).toHaveBeenCalledWith("thread-1");
    click("thread-2");                                                            // archived: never opened from outside
    click("@inbox");                                                              // the old route leads nowhere
    expect(selectConversation).toHaveBeenCalledTimes(1);
    expect(openSection).toHaveBeenCalledTimes(1);
  });

  it("is sent as @progress by the desktop shell, and no @inbox is left there or in the web app", () => {
    const shell = readFileSync(resolve(__dirname, "../../../desktop/src-tauri/src/resident.rs"), "utf8");
    expect(shell).toContain('"@progress"');
    expect(shell).not.toContain("@inbox");
    const sources = import.meta.glob(["../**/*.{ts,tsx}", "!../__tests__/**"], { query: "?raw", import: "default", eager: true });
    const left = Object.entries(sources).filter(([, text]) => String(text).includes("@inbox")).map(([path]) => path);
    expect(left).toEqual([]);
  });
});

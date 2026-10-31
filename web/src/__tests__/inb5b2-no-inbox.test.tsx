/** INB5b-2 (v0.1.64): the Inbox is gone (the INB5 board, approved 2026-10-31). What is waiting on you is one number on Progress in the
 *  sidebar, counted by the server (progress.waiting_on_user: conversations, projects and scheduled tasks, never rows); a clicked
 *  notice opens Progress; and no "@inbox" route is left anywhere. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/companion/BackgroundJobs", () => ({ default: () => null }));
vi.mock("../api/proactive", () => ({ PROACTIVE_CHANGED: "arslan:proactive-changed", proactiveApi: { summary: vi.fn() } }));

import { proactiveApi } from "../api/proactive";
import Sidebar from "../components/Sidebar";
import { useWaiting } from "../hooks/useWaiting";
import { notificationTarget, PROGRESS_TARGET } from "../lib/openConversation";
import { SECTIONS } from "../lib/sections";

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
    fireEvent.click(document.getElementById("nav-btn-activity-footer")!);
    expect(p.onChangeSection).toHaveBeenCalledWith("activity");
  });

  it("shows no number when nothing waits, and caps a big one", () => {
    const { rerender } = render(<Sidebar {...props({ waiting: 0 })} />);
    expect(screen.queryByTestId("progress-badge")).toBeNull();
    rerender(<Sidebar {...props({ waiting: 120 })} />);
    expect(screen.getByTestId("progress-badge")).toHaveTextContent("99+");
  });

  it("lists no inbox page", () => {
    expect(SECTIONS as readonly string[]).not.toContain("inbox");
  });
});

describe("the count", () => {
  it("is the server's waiting count, refreshed when anything changes, and kept when a poll fails", async () => {
    vi.mocked(proactiveApi.summary).mockResolvedValueOnce(summary(2) as never).mockResolvedValueOnce(summary(5) as never)
      .mockRejectedValueOnce(new Error("restarting"));
    const { result } = renderHook(() => useWaiting());
    await waitFor(() => expect(result.current.count).toBe(2));
    act(() => { window.dispatchEvent(new Event("arslan:proactive-changed")); });
    await waitFor(() => expect(result.current.count).toBe(5));
    act(() => { window.dispatchEvent(new Event("arslan:proactive-changed")); });
    await waitFor(() => expect(proactiveApi.summary).toHaveBeenCalledTimes(3));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });       // the failed poll has been handled
    expect(result.current.count).toBe(5);                                         // a restarting service does not zero it
  });
});

describe("a clicked notice", () => {
  it("opens Progress, and the old Inbox route leads nowhere", () => {
    expect(PROGRESS_TARGET).toBe("@progress");
    expect(notificationTarget("@progress", [])).toEqual({ kind: "progress" });
    expect(notificationTarget("@inbox", [])).toBeNull();
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

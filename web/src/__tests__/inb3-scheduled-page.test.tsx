/** INB3 (v0.1.64): the Scheduled page. Scheduled tasks and the watched pages and folders live in one place, out of Activity and the
 *  Inbox; a row is dotted when it needs a look, and a task's away entries are its own (the server keeps each conversation apart, #568). */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, renderHook, screen, fireEvent, cleanup, waitFor, within, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, params?: object) => (params ? `${key}:${JSON.stringify(params)}` : key),
    i18n: { language: "en", resolvedLanguage: "en" } }),
}));
vi.mock("../api/client", () => {
  class ApiError extends Error { status = 500; }
  return {
    ApiError,
    request: vi.fn(),
    api: { listScheduledTasks: vi.fn(), getScheduledTaskRuns: vi.fn(async () => []), listSpawns: vi.fn(async () => []),
      markScheduledTaskSeen: vi.fn(async () => ({ seen_at: "2026-11-01T10:00:00" })) },
  };
});
vi.mock("../api/proactive", () => ({
  PROACTIVE_CHANGED: "arslan:proactive-changed",
  announceProactiveChange: vi.fn(),
  proactiveApi: {
    items: vi.fn(), watches: vi.fn(), mutes: vi.fn(), scan: vi.fn(),
    accept: vi.fn(), snooze: vi.fn(), dismiss: vi.fn(), seen: vi.fn(),
  },
}));

import { api, request } from "../api/client";
import { announceProactiveChange, proactiveApi } from "../api/proactive";
import ScheduledPage from "../components/scheduled/ScheduledPage";
import Sidebar from "../components/Sidebar";
import NotDoneList from "../components/proactive/NotDoneList";
import { useScheduledAttention } from "../hooks/useScheduledAttention";

const setVisibility = (value: "visible" | "hidden") => Object.defineProperty(document, "visibilityState", { value, configurable: true });
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); setVisibility("visible"); });

const task = (id: number, over: Record<string, unknown> = {}) => ({
  id, name: `task ${id}`, prompt: "p", spawn_id: null, spawn_name: null, conversation_id: null, schedule_kind: "interval",
  interval_s: 3600, cron: null, enabled: true, last_fired_at: null, next_due_at: null, consecutive_failures: 0,
  paused_reason: null, created_at: null, last_outcome: "ok", ...over,
});
const item = (id: number, kind: string, source_key: string, diagnosis: unknown = null) => ({
  id, kind, title_key: `title.${kind}`, params: {}, evidence: [], goal: "g", priority: "normal", status: "new",
  diagnosis, conversation_id: null, job_id: null, created_at: "2026-10-31T08:00:00Z", snooze_until: null, source_key,
});
const away = (unattended: boolean, conversation_id = "conv-chat") => ({
  id: unattended ? 11 : 12, created_at: "2026-10-31T08:00:00Z", first_at: "2026-10-30T08:00:00Z", count: 2,
  conversation_id, kind: "send", target: "mail:team", detail: "send mail", always_ok: false, always: [], unattended,
});
const watch = (id: number, label: string) => ({ id, kind: "web", target: `https://example.com/${id}`, label, enabled: true,
  interval_s: 3600, notify: true, last_error: null, last_checked_at: null, last_changed_at: null });

function seed() {
  vi.mocked(api.listScheduledTasks).mockResolvedValue([
    task(1),                                                       // a problem reminder
    task(2, { enabled: false, paused_reason: "3 failures" }),      // paused itself
    task(3, { conversation_id: "conv-chat" }),                     // could not do something while you were away
    task(4),                                                       // fine
    task(5, { enabled: false }),                                   // paused by hand: no dot
    task(6, { last_outcome: "error" }),                            // its last run failed, not paused
    task(7, { conversation_id: "conv-only-chat" }),                // its conversation has only a chat turn's entry
  ] as never);
  vi.mocked(proactiveApi.items).mockResolvedValue({ items: [
    item(21, "scheduled_problem", "sched:1"),
    item(22, "web_change", "watch:7", { cause: "a new team plan", next_step: "compare the two", model: "m", usd: 0 }),
    item(23, "job_followup", "job:9"),
  ] } as never);
  vi.mocked(proactiveApi.watches).mockResolvedValue({ watches: [watch(7, "pricing"), watch(8, "downloads")] } as never);
  vi.mocked(proactiveApi.mutes).mockResolvedValue({ mutes: ["watch:9"] } as never);
  vi.mocked(proactiveApi.scan).mockResolvedValue({ created: 0, rejected: {} } as never);
  // Only a week's window holds them: the page's own list must ask for the same 168 hours as the dot (#585 review, C2).
  vi.mocked(request).mockImplementation((async (path: string) => {
    if (!path.startsWith("/approvals/refused?hours=168")) return [];
    if (path.includes("conversation_id=conv-chat")) return [away(true), away(false)];
    if (path.includes("conversation_id=conv-only-chat")) return [away(false, "conv-only-chat")];
    return [];
  }) as never);
}

/** `waiting`: the tasks the server counts as waiting on you (progress.waiting_on_user's `scheduled`, through useWaiting in App). */
function Page({ waiting = [1, 3] }: { waiting?: number[] }) {
  const attention = useScheduledAttention(waiting);
  return <ScheduledPage attention={attention} waitingTasks={waiting} onOpenConversation={() => {}} />;
}

describe("the Scheduled page", () => {
  it("dots the tasks the server counts as waiting, red when failing; a task whose entries were seen has none (INB5b-3)", async () => {
    seed();
    // 4: a card in its own conversation, which only the server sees (#590's re-check); 3: its entries were seen when its row was opened.
    render(<Page waiting={[1, 2, 4, 6]} />);
    await screen.findByTestId("sched-attention-1");
    const tone = (id: number) => screen.queryByTestId(`sched-attention-${id}`)?.getAttribute("data-tone") ?? null;
    expect([tone(1), tone(2), tone(4), tone(6)]).toEqual(["look", "failing", "look", "failing"]);
    expect([tone(3), tone(5), tone(7)]).toEqual([null, null, null]);   // seen; paused by hand; only a chat turn's entry
  });

  it("marks a task seen when its row is opened, tells the badge, and says what that clears (INB5b-3)", async () => {
    seed();
    render(<Page />);
    fireEvent.click(await screen.findByTestId("sched-expand-3"));
    await waitFor(() => expect(api.markScheduledTaskSeen).toHaveBeenCalledWith(3));
    await waitFor(() => expect(announceProactiveChange).toHaveBeenCalled());
    expect(await screen.findByText("scheduledPage.seenNote")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("sched-expand-3"));                     // closing it marks nothing
    expect(api.markScheduledTaskSeen).toHaveBeenCalledTimes(1);
  });

  it("asks for each task's away entries in that task's conversation, over a week", async () => {
    seed();
    render(<Page />);
    await screen.findByTestId("sched-attention-3");
    const asked = vi.mocked(request).mock.calls.map(([path]) => String(path)).filter((p) => p.startsWith("/approvals/refused"));
    expect(asked).toContain("/approvals/refused?hours=168&conversation_id=scheduled-1");
    expect(asked).toContain("/approvals/refused?hours=168&conversation_id=conv-chat");
  });

  it("shows a task's problem and its own away entries under its runs, without the chat turn's", async () => {
    seed();
    render(<Page />);
    fireEvent.click(await screen.findByTestId("sched-expand-3"));
    const section = await screen.findByRole("region", { name: "scheduledPage.awayTitle" });
    expect(within(section).getAllByTestId("inbox-refused-row")).toHaveLength(1);          // the scheduled run's, not the away card's
    fireEvent.click(screen.getByTestId("sched-expand-1"));
    expect(await screen.findByTestId("proactive-item-21")).toBeInTheDocument();
  });

  it("dots a watch whose page changed and shows the guess under it; the muted list is here too", async () => {
    seed();
    render(<Page />);
    const watch = await screen.findByTestId("proactive-watch-7");
    await waitFor(() => expect(within(watch).getByTestId("watch-attention-7")).toBeInTheDocument());
    expect(within(watch).getByTestId("proactive-diagnosis")).toHaveTextContent("a new team plan");
    expect(within(screen.getByTestId("proactive-watch-8")).queryByTestId("watch-attention-8")).toBeNull();
    expect(screen.getByTestId("proactive-mutes")).toBeInTheDocument();
  });

  it("checks now from here, and says what it found (moved from the Inbox's test, INB5b-2)", async () => {
    seed();
    vi.mocked(proactiveApi.scan).mockResolvedValueOnce({ created: 0, rejected: {} } as never).mockResolvedValueOnce({ created: 2, rejected: {} } as never);
    render(<Page />);
    fireEvent.click(await screen.findByText("proactive.page.checkNow"));
    expect(await screen.findByText('proactive.page.checkedNone:{"count":0}')).toBeInTheDocument();
    fireEvent.click(screen.getByText("proactive.page.checkNow"));
    expect(await screen.findByText('proactive.page.checkedSome:{"count":2}')).toBeInTheDocument();
    expect(proactiveApi.scan).toHaveBeenCalledTimes(2);
  });
});

describe("the sidebar's Scheduled entry", () => {
  const props = {
    threads: [], activeThreadId: "", activeSection: "arslan" as const, onSelectThread: () => {}, onAddThread: () => {},
    onChangeSection: vi.fn(), onArchiveThread: () => {}, onUnarchiveThread: () => {}, onDeleteThread: () => {},
    backendStatus: "online" as const,
  };
  it("opens the page, and carries a dot only when something there needs a look", () => {
    const { rerender } = render(<Sidebar {...props} />);
    fireEvent.click(screen.getByText("nav.scheduled"));
    expect(props.onChangeSection).toHaveBeenCalledWith("scheduled");
    expect(screen.queryByTestId("scheduled-dot")).toBeNull();
    rerender(<Sidebar {...props} scheduledDot />);
    expect(screen.getByTestId("scheduled-dot")).toBeInTheDocument();
  });
});

describe("NotDoneList for one conversation", () => {
  it("keeps the 24-hour list by default and asks for one conversation when given one", async () => {
    vi.mocked(request).mockResolvedValue([] as never);
    render(<NotDoneList />);
    await waitFor(() => expect(request).toHaveBeenCalledWith("/approvals/refused?hours=24"));
    cleanup();
    render(<NotDoneList conversationId="scheduled-4" hours={168} unattended />);
    await waitFor(() => expect(request).toHaveBeenCalledWith("/approvals/refused?hours=168&conversation_id=scheduled-4"));
  });
});

describe("the attention hook", () => {
  it("lights the sidebar for a task the server counts as waiting, and not for entries already seen (INB5b-3)", async () => {
    seed();
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [] } as never);   // no watch changed: only the server's count can light it
    const waiting = renderHook(() => useScheduledAttention([4]));
    await waitFor(() => expect(waiting.result.current.tasks[4]).toBeDefined());
    expect(waiting.result.current.any).toBe(true);
    waiting.unmount();
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [] } as never);   // task 3 still has away entries, but they were seen
    vi.mocked(api.listScheduledTasks).mockResolvedValue([task(3, { conversation_id: "conv-chat" })] as never);
    const seen = renderHook(() => useScheduledAttention([]));
    await waitFor(() => expect(seen.result.current.tasks[3]?.away).toBe(1));
    expect(seen.result.current.any).toBe(false);
  });

  it("lights the sidebar for a watch's change alone, but not for a removed watch's", async () => {
    vi.mocked(api.listScheduledTasks).mockResolvedValue([task(4)] as never);
    vi.mocked(request).mockResolvedValue([] as never);
    vi.mocked(proactiveApi.watches).mockResolvedValue({ watches: [watch(7, "pricing")] } as never);
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [item(22, "web_change", "watch:7")] } as never);
    const first = renderHook(() => useScheduledAttention());
    await waitFor(() => expect(first.result.current.any).toBe(true));
    first.unmount();
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [item(24, "web_change", "watch:99")] } as never);
    const second = renderHook(() => useScheduledAttention());
    await waitFor(() => expect(proactiveApi.items).toHaveBeenCalledTimes(2));
    await act(async () => { await Promise.resolve(); });
    expect(second.result.current.any).toBe(false);
    expect(second.result.current.changes).toEqual({});
  });

  it("reads once for a burst of changes, a moment after the last (#605 re-check N2)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    seed();
    renderHook(() => useScheduledAttention([]));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const calls = () => vi.mocked(api.listScheduledTasks).mock.calls.length;
    expect(calls()).toBe(1);
    act(() => { for (let i = 0; i < 3; i++) window.dispatchEvent(new Event("arslan:proactive-changed")); });   // an answer, an open, an Undo
    await act(async () => { await vi.advanceTimersByTimeAsync(999); });
    expect(calls()).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(calls()).toBe(2);                                                    // one read for the three, one request per task
  });

  it("stops polling when it goes away, waits while the window is hidden, and loads when it shows again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    seed();
    const hook = renderHook(() => useScheduledAttention());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const calls = () => vi.mocked(api.listScheduledTasks).mock.calls.length;
    expect(calls()).toBe(1);
    setVisibility("hidden");
    await act(async () => { await vi.advanceTimersByTimeAsync(31_000); });
    expect(calls()).toBe(1);                                                    // hidden: no poll
    setVisibility("visible");
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await vi.advanceTimersByTimeAsync(0); });
    expect(calls()).toBe(2);                                                    // shown again: at once
    hook.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(61_000); });
    expect(calls()).toBe(2);                                                    // gone: no more polls
  });
});

describe("outside text on the page", () => {
  it("shows bidi controls in a task's name, a watch's label and target, a page's quote and the guess as markers, and isolates title params", async () => {
    seed();
    vi.mocked(api.listScheduledTasks).mockResolvedValue([task(1, { name: "pay\u202Eroll" })] as never);
    vi.mocked(proactiveApi.watches).mockResolvedValue({ watches: [{ ...watch(7, "price\u202Elist"), target: "https://e.com/\u202Ex" }] } as never);
    vi.mocked(proactiveApi.items).mockResolvedValue({ items: [{
      ...item(22, "web_change", "watch:7", { cause: "cause\u202Ehere", next_step: "step\u202Etwo", model: "m", usd: 0 }),
      params: { label: "x\u202Ey" }, evidence: [{ key: "web.changed", params: { n: 2 }, quote: "line\u202Eend" }],
    }] } as never);
    render(<Page />);
    const row = await screen.findByTestId("sched-row");
    expect(within(row).getAllByTestId("escaped-control")).toHaveLength(1);
    const watchRow = await screen.findByTestId("proactive-watch-7");
    await waitFor(() => expect(within(watchRow).getByTestId("proactive-diagnosis")).toBeInTheDocument());
    const card = within(watchRow).getByTestId("proactive-item-22");
    const title = within(card).getByRole("heading").textContent ?? "";
    expect(title).toContain("\u2068xy\u2069");                             // isolated, the control dropped
    expect(title).not.toContain("\u202E");
    expect(within(card).getAllByTestId("escaped-control")).toHaveLength(2);    // the quote and the guess
    expect(within(card).getByTestId("proactive-diagnosis").textContent).toContain("\u2068steptwo\u2069");
    // label and target, beside the card's two
    expect(within(watchRow).getAllByTestId("escaped-control")).toHaveLength(4);
  });
});

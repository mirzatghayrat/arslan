/** INB3 (v0.1.64): the Scheduled page. Scheduled tasks and the watched pages and folders live in one place, out of Activity and the
 *  Inbox; a row is dotted when it needs a look, and a task's away entries are its own (the server keeps each conversation apart, #568). */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en", resolvedLanguage: "en" } }),
}));
vi.mock("../api/client", () => {
  class ApiError extends Error { status = 500; }
  return {
    ApiError,
    request: vi.fn(),
    api: { listScheduledTasks: vi.fn(), getScheduledTaskRuns: vi.fn(async () => []), listSpawns: vi.fn(async () => []) },
  };
});
vi.mock("../api/proactive", () => ({
  PROACTIVE_CHANGED: "arslan:proactive-changed",
  announceProactiveChange: () => {},
  proactiveApi: {
    items: vi.fn(), watches: vi.fn(), mutes: vi.fn(), scan: vi.fn(),
    accept: vi.fn(), snooze: vi.fn(), dismiss: vi.fn(), seen: vi.fn(),
  },
}));

import { api, request } from "../api/client";
import { proactiveApi } from "../api/proactive";
import ScheduledPage from "../components/scheduled/ScheduledPage";
import Sidebar from "../components/Sidebar";
import InboxRefused from "../components/proactive/InboxRefused";
import { useScheduledAttention } from "../hooks/useScheduledAttention";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const task = (id: number, over: Record<string, unknown> = {}) => ({
  id, name: `task ${id}`, prompt: "p", spawn_id: null, spawn_name: null, conversation_id: null, schedule_kind: "interval",
  interval_s: 3600, cron: null, enabled: true, last_fired_at: null, next_due_at: null, consecutive_failures: 0,
  paused_reason: null, created_at: null, last_outcome: "ok", ...over,
});
const item = (id: number, kind: string, source_key: string, diagnosis: unknown = null) => ({
  id, kind, title_key: `title.${kind}`, params: {}, evidence: [], goal: "g", priority: "normal", status: "new",
  diagnosis, conversation_id: null, job_id: null, created_at: "2026-10-31T08:00:00Z", snooze_until: null, source_key,
});
const away = (unattended: boolean) => ({
  id: unattended ? 11 : 12, created_at: "2026-10-31T08:00:00Z", first_at: "2026-10-30T08:00:00Z", count: 2,
  conversation_id: "conv-chat", kind: "send", target: "mail:team", detail: "send mail", always_ok: false, always: [], unattended,
});

function seed() {
  vi.mocked(api.listScheduledTasks).mockResolvedValue([
    task(1),                                                       // a problem reminder
    task(2, { enabled: false, paused_reason: "3 failures" }),      // paused itself
    task(3, { conversation_id: "conv-chat" }),                     // could not do something while you were away
    task(4),                                                       // fine
    task(5, { enabled: false }),                                   // paused by hand: no dot
  ] as never);
  vi.mocked(proactiveApi.items).mockResolvedValue({ items: [
    item(21, "scheduled_problem", "sched:1"),
    item(22, "web_change", "watch:7", { cause: "a new team plan", next_step: "compare the two", model: "m", usd: 0 }),
    item(23, "job_followup", "job:9"),
  ] } as never);
  vi.mocked(proactiveApi.watches).mockResolvedValue({ watches: [
    { id: 7, kind: "web", target: "https://example.com/pricing", label: "pricing", enabled: true, interval_s: 3600, notify: true,
      last_error: null, last_checked_at: null, last_changed_at: null },
    { id: 8, kind: "folder", target: "~/Downloads", label: "downloads", enabled: true, interval_s: 3600, notify: true,
      last_error: null, last_checked_at: null, last_changed_at: null },
  ] } as never);
  vi.mocked(proactiveApi.mutes).mockResolvedValue({ mutes: ["watch:9"] } as never);
  vi.mocked(proactiveApi.scan).mockResolvedValue({ created: 0, rejected: {} } as never);
  vi.mocked(request).mockImplementation((async (path: string) =>
    (path.startsWith("/approvals/refused") && path.includes("conversation_id=conv-chat") ? [away(true), away(false)] : [])) as never);
}

function Page() {
  const attention = useScheduledAttention();
  return <ScheduledPage attention={attention} onOpenConversation={() => {}} />;
}

describe("the Scheduled page", () => {
  it("dots the tasks that need a look, and only those", async () => {
    seed();
    render(<Page />);
    await screen.findByTestId("sched-attention-1");
    expect(screen.getByTestId("sched-attention-2")).toBeInTheDocument();
    expect(screen.getByTestId("sched-attention-3")).toBeInTheDocument();
    expect(screen.queryByTestId("sched-attention-4")).toBeNull();
    expect(screen.queryByTestId("sched-attention-5")).toBeNull();
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

  it("checks now from here", async () => {
    seed();
    render(<Page />);
    fireEvent.click(await screen.findByText("proactive.page.checkNow"));
    await waitFor(() => expect(proactiveApi.scan).toHaveBeenCalledTimes(1));
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

describe("InboxRefused for one conversation", () => {
  it("keeps the 24-hour list for the Inbox and asks for one conversation when given one", async () => {
    vi.mocked(request).mockResolvedValue([] as never);
    render(<InboxRefused />);
    await waitFor(() => expect(request).toHaveBeenCalledWith("/approvals/refused?hours=24"));
    cleanup();
    render(<InboxRefused conversationId="scheduled-4" hours={168} unattended />);
    await waitFor(() => expect(request).toHaveBeenCalledWith("/approvals/refused?hours=168&conversation_id=scheduled-4"));
  });
});

/** SUB5a follow-up to #799: a scheduled task paused because its conversation was deleted (`paused_reason` and the reminder's
 *  `reason` are `conversation_deleted`). The Inbox's reminder words it as the Scheduled page does, a clicked Mac notification
 *  opens the task on the Scheduled page (never the deleted conversation), and the sentence for "Do it" refused on a deleted
 *  conversation names what can be done: Do it always sends the item's own conversation. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const listeners = vi.hoisted(() => new Map<string, (event: { payload: unknown }) => void>());
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (name: string, handler: (event: { payload: unknown }) => void) => {
    listeners.set(name, handler);
    return () => listeners.delete(name);
  }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en", resolvedLanguage: "en" } }),
}));
vi.mock("../api/client", () => {
  class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
  return { ApiError, request: vi.fn(), api: { listScheduledTasks: vi.fn(), getScheduledTaskRuns: vi.fn() } };
});
vi.mock("../api/proactive", () => ({
  PROACTIVE_CHANGED: "arslan:proactive-changed",
  announceProactiveChange: () => {},
  proactiveApi: { items: vi.fn(), accept: vi.fn(), snooze: vi.fn(), dismiss: vi.fn() },
}));

import { api, ApiError } from "../api/client";
import { proactiveApi } from "../api/proactive";
import ScheduledTasksCard from "../components/ScheduledTasksCard";
import { useReminderActions } from "../components/proactive/reminders";
import { useNotificationRoutes } from "../hooks/useNotificationRoutes";
import { evidenceLines } from "../lib/proactive";
import { proactiveMessages } from "../locales/proactive";

const LANGS = ["en", "zh", "ja", "es", "de", "fr"] as const;
const t = ((key: string) => key) as never;

beforeEach(() => {
  (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = { invoke: vi.fn() };
});
afterEach(() => {
  cleanup(); vi.clearAllMocks(); listeners.clear();
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

describe("the Inbox's reminder for a task paused on a deleted conversation", () => {
  it("is the Scheduled page's sentence, not a count of failures", () => {
    const [line] = evidenceLines(t, "en", [{ key: "sched.state",
      params: { name: "daily", failures: 0, paused: true, reason: "conversation_deleted" } }]);
    expect(line.text).toBe("scheduled.reason.conversation_deleted");
    expect(line.quote).toBeUndefined();
    const [failed] = evidenceLines(t, "en", [{ key: "sched.state", params: { name: "daily", failures: 3, paused: true } }]);
    expect(failed.text).toBe("proactive.evidence.sched.state.paused");
    const [unknown] = evidenceLines(t, "en", [{ key: "sched.state", params: { name: "d", failures: 3, paused: true, reason: "x" } }]);
    expect(unknown.text).toBe("proactive.evidence.sched.state.paused");   // a code the page doesn't word reads as before
  });
});

describe("Do it, refused because the item's conversation was deleted", () => {
  it("sends the item's own conversation, and the sentence names what works: dismissing it", async () => {
    vi.mocked(proactiveApi.accept).mockRejectedValue(new ApiError("conversation_deleted", 422));
    const { result } = renderHook(() => useReminderActions({ reload: async () => {}, onOpenConversation: vi.fn() }));
    await act(() => result.current.doIt({ id: 5, conversation_id: "thread-gone" } as never));
    expect(proactiveApi.accept).toHaveBeenCalledWith(5, undefined);    // its own conversation, whichever one is open
    expect(result.current.notice?.text).toBe("proactive.item.errors.conversation_deleted");
    for (const lang of LANGS) {
      const item = proactiveMessages[lang].item as unknown as { notUseful: string; errors: Record<string, string> };
      expect(item.errors.conversation_deleted, lang).toContain(item.notUseful);
    }
    expect(proactiveMessages.en.item.errors.conversation_deleted).not.toMatch(/another conversation/i);
  });
});

describe("a clicked notification of that pause", () => {
  it("opens the task on the Scheduled page; the shell's event name is the one the Mac emits", async () => {
    const openScheduledTask = vi.fn();
    const selectConversation = vi.fn();
    renderHook(() => useNotificationRoutes({ threads: [{ id: "thread-1" }], selectConversation, openScheduledTask }));
    await waitFor(() => expect([...listeners.keys()].sort()).toEqual(["open-conversation", "open-scheduled-task"]));
    act(() => listeners.get("open-scheduled-task")!({ payload: 7 }));
    expect(openScheduledTask).toHaveBeenCalledWith(7);
    for (const payload of [0, -1, 1.5, "7", null]) act(() => listeners.get("open-scheduled-task")!({ payload }));
    expect(openScheduledTask).toHaveBeenCalledTimes(1);
    expect(selectConversation).not.toHaveBeenCalled();
    const shell = readFileSync(resolve(__dirname, "../../../desktop/src-tauri/src/resident.rs"), "utf8");
    expect(shell).toContain('OPEN_SCHEDULED_TASK_EVENT: &str = "open-scheduled-task"');
  });

  it("opens that task's row on the Scheduled page, once per click", async () => {
    vi.mocked(api.listScheduledTasks).mockResolvedValue([
      { id: 3, name: "Other", prompt: "p", enabled: true, schedule_kind: "interval", interval_s: 3600, paused_reason: null },
      { id: 7, name: "Lost task", prompt: "p", enabled: false, schedule_kind: "interval", interval_s: 3600,
        paused_reason: "conversation_deleted" },
    ] as never);
    vi.mocked(api.getScheduledTaskRuns).mockResolvedValue([] as never);
    const onOpen = vi.fn();
    const { rerender } = render(<ScheduledTasksCard onOpen={onOpen} focus={{ taskId: 7, n: 1 }} />);
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(7));
    expect(api.getScheduledTaskRuns).toHaveBeenCalledWith(7);
    expect(await screen.findByTestId("sched-history")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("sched-expand-7"));                // closed by hand: it stays closed
    rerender(<ScheduledTasksCard onOpen={onOpen} focus={{ taskId: 7, n: 1 }} />);
    expect(screen.queryByTestId("sched-history")).toBeNull();
    rerender(<ScheduledTasksCard onOpen={onOpen} focus={{ taskId: 7, n: 2 }} />);   // a second click opens it again
    expect(await screen.findByTestId("sched-history")).toBeInTheDocument();
    expect(onOpen).toHaveBeenCalledTimes(2);
    rerender(<ScheduledTasksCard onOpen={onOpen} focus={{ taskId: 99, n: 3 }} />);  // a task the list doesn't have
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});

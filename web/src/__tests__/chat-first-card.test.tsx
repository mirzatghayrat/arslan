/** 0.1.61 §A4 (PR 2b final review): a card that comes up where no card was — in a chat slot that has been empty a while — is not answered
 *  by a click or a ⌘⏎ that lands on it within ANSWER_GUARD_MS: that gesture was aimed at what was there (a message, a link, a job's
 *  card). The island holds the same way on mount (IslandApp AskView). 500 ms later it answers normally. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { ANSWER_GUARD_MS } from "../components/kit";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const cmd = { type: "propose_run_command", call_id: "late", pretty: "rm -rf ~/Documents", reason: "", options: ["once", "conversation", "always"],
  always_label: "deletes files", perm_kind: "command" };

describe("a card that comes up where none was", () => {
  it("is not answered by a click that lands on it at once; 500 ms later it is", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    advance(5_000);                                                  // the slot has been empty a while
    frame(cmd);                                                      // a job asks, over the chat the person is clicking in
    fireEvent.click(screen.getByTestId("runcmd-run"));
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByTestId("runcmd-run")).toHaveAttribute("aria-disabled", "true");
    advance(ANSWER_GUARD_MS);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "late", scope: "once" }]]);
  });
});

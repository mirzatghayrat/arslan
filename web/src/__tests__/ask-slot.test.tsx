/** 0.1.55 S2: every pending ask in ONE slot — queued, answered with ⌘⏎ / esc,
 *  the same confirm / cancel frames as before for a frame without choices, a countdown from the
 *  frame's arrival (its own expires_at when it has one: card-v2.test.tsx). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import AskSlot from "../components/AskSlot";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => { cleanup(); vi.useRealTimers(); });

const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

describe("the ask slot", () => {
  it("two waiting asks show as ONE card, oldest first, and ⌘⏎ answers it with the same frame as before", () => {
    vi.useFakeTimers();                                                  // the card that moves up answers after the answer guard (500 ms)
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ type: "propose_run_command", call_id: "c1", command: "git", argv: ["status"], pretty: "git status", reason: "" });
    frame({ type: "propose_action", call_id: "a1", kind: "mac_script", target: "Notes",
            detail: 'tell application "Notes"\n  delete (notes whose name = "x")\nend tell' });
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    expect(screen.getByTestId("runcmd-card")).toBeInTheDocument();
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('"index":1,"total":2');
    // 0.1.61: a frame without expires_at waits the Mac's 30 minutes (approvals.TIMEOUT_S), not 5.
    expect(screen.getByTestId("ask-countdown")).toHaveAccessibleName(/^(30:00|29:\d\d)$/);
    act(() => { vi.advanceTimersByTime(500); });                         // c1 came up where none was: it answers once the guard has run out
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "c1", remember: false });
    // the next one moves up; its risk line is read from the script
    expect(screen.getByTestId("action-card")).toBeInTheDocument();
    expect(screen.getByTestId("ask-risk")).toHaveTextContent("kit.riskLine");
    act(() => { vi.advanceTimersByTime(500); });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).toHaveBeenLastCalledWith({ type: "cancel_action", call_id: "a1" });
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });

  it("the one that arrived first is shown first, whatever its kind", () => {
    // Both arrive before the slot is shown (e.g. the chat was on another page), so
    // only the arrival order — not which card was already on screen — decides.
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(1_000);
    frame({ type: "propose_action", call_id: "a0", kind: "browser_site", target: "example.com", detail: "click Buy" });
    now.mockReturnValue(2_000);
    frame({ type: "propose_run_command", call_id: "c0", command: "ls", argv: [], pretty: "ls", reason: "" });
    now.mockRestore();
    render(<AskSlot send={vi.fn()} />);
    expect(screen.getByTestId("action-card")).toBeInTheDocument();
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
  });

  it("plain ⏎ while typing never answers", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ type: "propose_run_command", call_id: "c2", command: "ls", argv: [], pretty: "ls", reason: "" });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(send).not.toHaveBeenCalled();
  });

  it("a card answered elsewhere (card_resolved) leaves the queue", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_schedule", call_id: "s1", name: "早报", when: "every: 86400" });
    expect(screen.getByTestId("schedule-card")).toBeInTheDocument();
    frame({ type: "card_resolved", call_id: "s1", outcome: "approved", by: "phone" });
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });
});

/** 0.1.55 S2: every pending ask in ONE slot — queued, answered with ⌘⏎ / esc,
 *  the same confirm / cancel frames as before, a countdown from the frame's arrival. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import AskSlot from "../components/AskSlot";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => cleanup());

const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

describe("the ask slot", () => {
  it("two waiting asks show as ONE card, oldest first, and ⌘⏎ answers it with the same frame as before", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ type: "propose_run_command", call_id: "c1", command: "git", argv: ["status"], pretty: "git status", reason: "" });
    frame({ type: "propose_action", call_id: "a1", kind: "mac_script", target: "Notes",
            detail: 'tell application "Notes"\n  delete (notes whose name = "x")\nend tell' });
    expect(screen.getAllByRole("alertdialog")).toHaveLength(1);
    expect(screen.getByTestId("runcmd-card")).toBeInTheDocument();
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('"index":1,"total":2');
    expect(screen.getByTestId("ask-countdown")).toHaveAccessibleName(/^[45]:\d\d$/);
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "c1", remember: false });
    // the next one moves up; its risk line is read from the script
    expect(screen.getByTestId("action-card")).toBeInTheDocument();
    expect(screen.getByTestId("ask-risk")).toHaveTextContent("kit.riskLine");
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

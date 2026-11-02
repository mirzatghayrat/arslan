/** #605 review F4: what clears the count on Progress announces it, so the badge follows at once instead of up to 30 s later: a card
 *  answered in the slot, a card answered elsewhere (`card_resolved`), and "Always allow" and its Undo. useWaiting reads again a moment
 *  after a change, so a count read before the server applied it does not stand. (Opening a conversation is in inb4-done-unseen.) */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: "en" } }),
}));

import * as client from "../api/client";
import { PROACTIVE_CHANGED } from "../api/proactive";
import AskSlot from "../components/AskSlot";
import NotDoneList from "../components/proactive/NotDoneList";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-01T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const listening: (() => void)[] = [];
afterEach(() => { listening.splice(0).forEach((listener) => window.removeEventListener(PROACTIVE_CHANGED, listener)); });
const heard = () => {
  const listener = vi.fn();
  window.addEventListener(PROACTIVE_CHANGED, listener);
  listening.push(listener);
  return listener;
};
const row = (id: number) => ({ id, created_at: "2026-11-01T09:00:00Z", first_at: "2026-11-01T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail: "mail -s hi me@x.com", always_ok: true,
  always: [{ kind: "legacy_rule", target: "send-mail", label: "sends email" }], unattended: false });

describe("what clears the count announces it", () => {
  it("a card answered in the slot", async () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ type: "propose_run_command", call_id: "a", pretty: "echo hi", reason: "", options: ["once", "conversation", "always"],
      always_label: "that command", perm_kind: "command" });
    await settle(600);
    const listener = heard();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
    expect(listener).toHaveBeenCalled();
  });

  it("a card answered elsewhere: the phone, the island, another window", () => {
    const listener = heard();
    frame({ type: "card_resolved", call_id: "b", outcome: "approved" });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("an 「Always allow」 and its Undo", async () => {
    vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
      if (path.startsWith("/approvals/refused")) return [row(7)];
      if (path === "/permissions/rules" && init?.method === "POST") return { rules: [{ id: 99 }] };
      return { ok: true };
    }) as never);
    render(<NotDoneList conversationId="c" />);
    await settle(600);
    const listener = heard();
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await settle();
    expect(listener).toHaveBeenCalledTimes(1);
    await settle(500);
    fireEvent.click(screen.getByTestId("inbox-refused-undo"));
    await settle();
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

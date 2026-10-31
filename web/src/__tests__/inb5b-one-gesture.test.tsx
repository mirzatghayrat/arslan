/** INB5b (v0.1.64): one gesture answers one thing in the conversation too. The ask slot floats above the composer and what wasn't done
 *  while you were away sits on top of the messages, so in a short conversation a card leaving the slot can leave an "Always allow" row
 *  under the pointer. The window keeps ONE guard for both, as the Inbox did: a card answered, or an entry list that changes, holds the
 *  other for 500 ms. AskSlot takes the guard of the scope above it when there is one (App puts the slot and the conversation in one). */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: "en" } }),
}));

import * as client from "../api/client";
import AskSlot from "../components/AskSlot";
import { AwayEntries } from "../components/conversation/WhileAway";
import { AnswerGuardScope, makeAnswerGuard } from "../components/kit/guard";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-01T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
// React draws what one act schedules only when the act ends: a step at a time, so each list is drawn when it arrives.
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const cmd = (id: string, pretty: string) => ({ type: "propose_run_command", call_id: id, pretty, reason: "",
  options: ["once", "conversation", "always"], always_label: "that command", perm_kind: "command" });
const row = (id: number, detail: string) => ({ id, created_at: "2026-11-01T09:00:00Z", first_at: "2026-11-01T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail, always_ok: true, always: [{ kind: "legacy_rule", target: "send-mail", label: "sends email" }],
  unattended: false });

function serve(refused: () => unknown[]) {
  const calls: string[] = [];
  vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${path}`);
    if (path.startsWith("/approvals/refused")) return refused();
    if (path === "/permissions/rules") return { rules: [{ id: 99 }] };
    return { ok: true };
  }) as never);
  return calls;
}

describe("one gesture answers one thing in the conversation", () => {
  it("the second click of a double-click on Run is not an 'Always allow' on the entry left under the pointer", async () => {
    const calls = serve(() => [row(7, "mail -s hi me@x.com")]);
    const send = vi.fn();
    render(<AnswerGuardScope value={makeAnswerGuard()}><AskSlot send={send} /><AwayEntries conversationId="c" /></AnswerGuardScope>);
    frame(cmd("a", "echo harmless"));
    await settle(600);                                               // the card and the entries have been there for 500 ms
    fireEvent.click(screen.getByTestId("runcmd-run"));               // click 1 answers the card, which leaves the slot
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));      // click 2, on the entry now under the pointer
    await settle();
    expect(calls).not.toContain("POST /permissions/rules");
    await settle(500);                                               // aimed at on purpose later, it is taken
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await settle();
    expect(calls).toContain("POST /permissions/rules");
  });

  it("the slot takes the guard of the scope above it: a hold from outside holds its card", async () => {
    serve(() => []);
    const guard = makeAnswerGuard();
    const send = vi.fn();
    render(<AnswerGuardScope value={guard}><AskSlot send={send} /></AnswerGuardScope>);
    frame(cmd("a", "echo harmless"));
    await settle(600);
    act(() => { guard.hold(); });                                    // the entries above it changed
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).not.toHaveBeenCalled();
    await settle(500);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
  });
});

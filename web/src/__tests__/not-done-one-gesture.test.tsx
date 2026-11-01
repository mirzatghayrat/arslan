/** 0.1.61 §A4 (PR 2b final review), moved from inbox-one-gesture.test.tsx when the Inbox went (INB5b-2): "Not done while you were away"
 *  (NotDoneList) holds the guard of the scope above it when its list changes, and never takes the ask queue's place in it. The file's other
 *  cases moved too: a double-click on Run landing on "Always allow" (inb5b-one-gesture, now across the ask slot and the conversation), and a
 *  card that comes up being held (answer-guard, I3). Its case of a list change holding the card above it went with the Inbox's layout. */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import * as client from "../api/client";
import NotDoneList from "../components/proactive/NotDoneList";
import { AnswerGuardScope, makeAnswerGuard } from "../components/kit/guard";


beforeEach(() => {
  void i18n.changeLanguage("en");
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
// React draws what one act schedules only when the act ends: a step at a time, so each list is drawn when it arrives.
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };

const row = (id: number, detail: string) => ({ id, created_at: "2026-10-13T09:00:00Z", first_at: "2026-10-13T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail, always_ok: true, always: [{ kind: "legacy_rule", target: "send-mail", label: "sends email" }] });

/** The server behind the Inbox: what is waiting and what was not done, as the test says; every call is written down. */
function serve(waiting: () => unknown[], refused: () => unknown[]) {
  const calls: string[] = [];
  vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${path}`);
    if (path === "/approvals/pending") return waiting();
    if (path.startsWith("/approvals/refused")) return refused();
    if (path === "/permissions/rules") return { rules: [{ id: 99 }] };
    return { ok: true };
  }) as never);
  return calls;
}

describe("Not done while you were away and the guard above it", () => {
  it("the 'not done' list holds the shared guard but never takes the waiting card's place in it: the queue alone owns which card is on top", async () => {
    const guard = makeAnswerGuard();
    guard.shown("card-a");                                           // the queue above has its card on top
    serve(() => [], () => [row(7, "mail -s hi me@x.com")]);
    render(<AnswerGuardScope value={guard}><NotDoneList /></AnswerGuardScope>);
    await settle(30);                                                // the list appears: it pushes the content down, so it holds
    expect(guard.held()).toBe(true);
    await settle(600);
    expect(guard.held()).toBe(false);
    guard.shown("card-a");                                           // the same card again is no change — whatever the list did meanwhile
    expect(guard.held()).toBe(false);
  });
});

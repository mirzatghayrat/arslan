/** 0.1.61 §A4 (PR 2b final review): one gesture answers one thing in the Inbox, across its sections. The waiting cards ("Approve now") sit
 *  above "Not done while you were away", and each section is drawn only while it has something: when one appears, changes or goes, the
 *  other moves under the pointer. So the Inbox keeps ONE guard for both (ProactiveInbox): a card answered, a card that appears, a list
 *  that changes — for 500 ms neither a card's Allow nor an "Always allow" is taken. Real i18n (English), as proactive-inbox.test.tsx. */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import * as client from "../api/client";
import ProactiveInbox from "../components/proactive/ProactiveInbox";
import InboxRefused from "../components/proactive/InboxRefused";
import { AnswerGuardScope, makeAnswerGuard } from "../components/kit/guard";

const api = vi.hoisted(() => ({
  items: vi.fn(), accept: vi.fn(), snooze: vi.fn(), dismiss: vi.fn(), seen: vi.fn(), scan: vi.fn(),
}));
vi.mock("../api/proactive", async (original) => ({ ...(await original<typeof import("../api/proactive")>()), proactiveApi: api }));

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.items.mockResolvedValue({ items: [] });
  api.seen.mockResolvedValue({ ok: true });
  void i18n.changeLanguage("en");
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
// React draws what one act schedules only when the act ends: a step at a time, so each list is drawn when it arrives.
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };

const ask = (id: string, pretty: string) => ({ call_id: id, conversation_id: "conv-1", opened_at: Date.now() / 1000, expires_at: Date.now() / 1000 + 1700,
  frame: { type: "propose_run_command", call_id: id, pretty, reason: "", options: ["once", "conversation", "always"], always_label: "deletes files",
           perm_kind: "command" } });
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

describe("the Inbox: one gesture answers one thing, across its sections", () => {
  it("the second click of a double-click on the last card's Run is not an 'Always allow' on the row that moved up into its place", async () => {
    let answered = false;
    const calls = serve(() => (answered ? [] : [ask("a", "echo harmless")]), () => [row(7, "mail -s hi me@x.com")]);
    render(<ProactiveInbox onOpenSettings={vi.fn()} onOpenConversation={vi.fn()} onOpenModelSettings={vi.fn()} />);
    await settle(600);
    fireEvent.click(screen.getByTestId("runcmd-run"));               // click 1
    answered = true;
    await settle(30);                                                // the card's section is gone: the rows moved up
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));      // click 2, on the row now under the pointer
    await settle();
    expect(calls).toContain("POST /approvals/a/answer");
    expect(calls).not.toContain("POST /permissions/rules");
    await settle(500);                                               // aimed at on purpose later, it is taken
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await settle();
    expect(calls).toContain("POST /permissions/rules");
  });

  it("a card that appears at the top, pushing the rows down, is not answered by a click that lands on it at once; 500 ms later it is", async () => {
    let polls = 0;
    const calls = serve(() => (polls++ === 0 ? [] : [ask("b", "rm -rf ~/Documents")]), () => [row(7, "mail -s hi me@x.com")]);
    render(<ProactiveInbox onOpenSettings={vi.fn()} onOpenConversation={vi.fn()} onOpenModelSettings={vi.fn()} />);
    await settle(600);
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
    await settle(4_500);                                             // the 5 s poll: the section appears above the rows
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("rm -rf ~/Documents");
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await settle();
    expect(calls).not.toContain("POST /approvals/b/answer");
    await settle(500);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await settle();
    expect(calls).toContain("POST /approvals/b/answer");
  });

  it("a change in the 'not done' list holds the card above it too", async () => {
    let rows = [row(7, "mail -s hi me@x.com")];
    const calls = serve(() => [ask("c", "git push")], () => rows);
    render(<ProactiveInbox onOpenSettings={vi.fn()} onOpenConversation={vi.fn()} onOpenModelSettings={vi.fn()} />);
    await settle(600);
    rows = [row(8, "mail -s again me@x.com"), row(7, "mail -s hi me@x.com")];
    await settle(29_500);                                            // the list's 30 s poll: a new entry
    expect(screen.getAllByTestId("inbox-refused-row")).toHaveLength(2);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await settle();
    expect(calls).not.toContain("POST /approvals/c/answer");
  });
  it("the 'not done' list holds the shared guard but never takes the waiting card's place in it: the queue alone owns which card is on top", async () => {
    const guard = makeAnswerGuard();
    guard.shown("card-a");                                           // the queue above has its card on top
    serve(() => [], () => [row(7, "mail -s hi me@x.com")]);
    render(<AnswerGuardScope value={guard}><InboxRefused /></AnswerGuardScope>);
    await settle(30);                                                // the list appears: it pushes the content down, so it holds
    expect(guard.held()).toBe(true);
    await settle(600);
    expect(guard.held()).toBe(false);
    guard.shown("card-a");                                           // the same card again is no change — whatever the list did meanwhile
    expect(guard.held()).toBe(false);
  });
});

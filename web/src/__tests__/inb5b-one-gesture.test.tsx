/** INB5b (v0.1.64): one gesture answers one thing in the conversation too. The ask slot floats above the composer and what wasn't done
 *  while you were away sits on top of the messages, so in a short conversation a card leaving the slot can leave an "Always allow" row
 *  under the pointer. The window keeps ONE guard for both, as the Inbox did: a card answered, or an entry list that changes, holds the
 *  other for 500 ms. AskSlot takes the guard of the scope above it when there is one (App puts the slot and the conversation in one).
 *  #602 review (finding 1): a stopped job's card at the end of the conversation is the likeliest thing under the slot, and its
 *  「接着做」 starts a job, so it answers to the same guard and holds it when it comes up or changes. Finding 3: a scroll that moves the
 *  away rows under a still pointer (a reply streaming in) holds their clicks, but not the slot's card, which does not move. */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: "en" } }),
}));

import * as client from "../api/client";
import AskSlot from "../components/AskSlot";
import { AwayEntries, StoppedJobCards } from "../components/conversation/WhileAway";
import { ReminderCard } from "../components/proactive/reminders";
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

const job = (id: number) => ({ id, kind: "job_followup", title_key: "title.job_followup", params: { goal: "x" }, evidence: [],
  goal: "Finish the report.", priority: "normal", status: "new", diagnosis: null, conversation_id: "c", job_id: "j1",
  created_at: "2026-11-01T09:00:00", snooze_until: null });

function serve(refused: () => unknown[], jobs: unknown[] = []) {
  const calls: string[] = [];
  vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${path}`);
    if (path.startsWith("/approvals/refused")) return refused();
    if (path === "/permissions/rules") return { rules: [{ id: 99 }] };
    if (path.startsWith("/proactive/items?")) return { items: jobs };
    if (/^\/proactive\/items\/\d+\/accept$/.test(path)) return { job_id: "j2", conversation_id: "c" };
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

  it("the second click of a double-click on Run is not a 「接着做」 on the stopped job left under the pointer", async () => {
    const calls = serve(() => [], [job(5)]);
    const send = vi.fn();
    render(<AnswerGuardScope value={makeAnswerGuard()}><AskSlot send={send} />
      <StoppedJobCards conversationId="c" onOpenConversation={vi.fn()} /></AnswerGuardScope>);
    frame(cmd("a", "echo harmless"));
    await settle(600);
    fireEvent.click(screen.getByTestId("runcmd-run"));               // click 1 answers the card, which leaves the slot
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
    fireEvent.click(screen.getByText("proactive.item.doIt"));         // click 2, on the stopped job's card now under the pointer
    await settle();
    expect(calls).not.toContain("POST /proactive/items/5/accept");
    await settle(500);                                               // aimed at on purpose later, it starts the job
    fireEvent.click(screen.getByText("proactive.item.doIt"));
    await settle();
    expect(calls).toContain("POST /proactive/items/5/accept");
  });

  it("a stopped job's card that comes up holds the slot's card", async () => {
    serve(() => [], [job(5)]);
    const send = vi.fn();
    const guard = makeAnswerGuard();
    const { rerender } = render(<AnswerGuardScope value={guard}><AskSlot send={send} /></AnswerGuardScope>);
    frame(cmd("a", "echo harmless"));
    await settle(600);
    rerender(<AnswerGuardScope value={guard}><AskSlot send={send} />
      <StoppedJobCards conversationId="c" onOpenConversation={vi.fn()} /></AnswerGuardScope>);
    await settle();                                                  // its list arrives: the card comes up and moves what is around it
    expect(screen.getByText("proactive.item.doIt")).toBeTruthy();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).not.toHaveBeenCalled();
    await settle(500);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
  });

  it("while the guard holds, none of a reminder's doors answers: Do it, Snooze, each Not useful, Got it", async () => {
    const guard = makeAnswerGuard();
    const doors = { onDo: vi.fn(), onSnooze: vi.fn(), onDismiss: vi.fn(), onOpenConversation: vi.fn() };
    const web = { ...job(6), kind: "web_change", title_key: "title.web_change", params: { label: "Pricing" } };   // has a source to stop
    const brief = { ...job(7), kind: "brief", title_key: "title.brief", params: {} };                            // read-only: Got it
    render(<AnswerGuardScope value={guard}>
      {[job(5), web, brief].map((item) => <ReminderCard key={item.id} item={item as never} busy={false} language="en" {...doors} />)}
    </AnswerGuardScope>);
    const card = (id: number) => within(screen.getByTestId(`proactive-item-${id}`));
    const choose = (id: number, menu: string, choice: string) => {
      fireEvent.click(card(id).getByText(menu));
      fireEvent.click(card(id).getByText(choice));
    };
    const tryAll = () => {
      fireEvent.click(card(5).getByText("proactive.item.doIt"));
      choose(5, "proactive.item.snooze", "proactive.item.snooze3");
      choose(5, "proactive.item.notUseful", "proactive.item.dismissOnly");
      choose(5, "proactive.item.notUseful", "proactive.item.stopKind");
      choose(6, "proactive.item.notUseful", "proactive.item.stopSource");
      fireEvent.click(card(7).getByText("proactive.item.gotIt"));
    };
    act(() => { guard.hold(); });
    tryAll();
    expect(doors.onDo).not.toHaveBeenCalled();
    expect(doors.onSnooze).not.toHaveBeenCalled();
    expect(doors.onDismiss).not.toHaveBeenCalled();
    await settle(500);
    tryAll();
    expect(doors.onDo).toHaveBeenCalledOnce();
    expect(doors.onSnooze).toHaveBeenCalledWith(3);
    expect(doors.onDismiss.mock.calls).toEqual([[], ["kind"], ["source"], []]);
  });

  it("a scroll that moves the away rows under a still pointer holds their 「Always allow」, and only theirs", async () => {
    const calls = serve(() => [row(7, "mail -s hi me@x.com")]);
    const send = vi.fn();
    render(<AnswerGuardScope value={makeAnswerGuard()}><AskSlot send={send} />
      <div data-testid="conversation"><AwayEntries conversationId="c" /></div></AnswerGuardScope>);
    frame(cmd("a", "echo harmless"));
    await settle(600);
    fireEvent.scroll(screen.getByTestId("conversation"));            // a reply streams in; the conversation, stuck to the bottom, scrolls
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await settle();
    expect(calls).not.toContain("POST /permissions/rules");
    fireEvent.click(screen.getByTestId("runcmd-run"));               // the slot floats and did not move: its card answers
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
    await settle(500);
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

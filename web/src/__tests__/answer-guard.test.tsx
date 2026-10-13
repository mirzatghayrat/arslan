/** 0.1.61 §A4 (PR 2b Task 3, fix round 2, F2): one gesture answers one card. For 500 ms after the card on top of the queue changes
 *  (the one before it was answered, resolved elsewhere, ran out or was paged away), nothing answers the new one — not a click on
 *  Allow, on No or on a scope, not ⌘⏎, not Esc — so a double-click or a second key press aimed at the card that just left can never
 *  land, unread, on the one that moved up (a double-click confirmed `echo harmless` AND `rm -rf ~/Documents` in a real browser).
 *  The slot being empty for a moment does not end it: a card that comes up within 500 ms of the one that left is held for the rest of
 *  that time (the next command of the same turn is proposed as soon as the first ran). A card that comes up in a slot that has been
 *  empty longer, and paging, are not guarded. F4: while the card on top is busy, ‹ and › are disabled. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import * as client from "../api/client";
import AskSlot from "../components/AskSlot";
import { AskCard, AskQueue, ANSWER_GUARD_MS } from "../components/kit";
import { makeAnswerGuard } from "../components/kit/guard";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const cmd = (id: string, pretty: string, extra: Record<string, unknown> = {}) => ({ type: "propose_run_command", call_id: id, pretty, reason: "",
  options: ["once", "conversation", "always"], always_label: "that command", perm_kind: "command", ...extra });
const run = () => fireEvent.click(screen.getByTestId("runcmd-run"));
const cmdKey = (init: KeyboardEventInit) => fireEvent.keyDown(window, { key: "Enter", ...init });

/** two commands: the harmless one the person means to answer, and the one that moves up behind it */
function twoCommands(send = vi.fn()) {
  render(<AskSlot send={send} />);
  frame(cmd("safe-one", "echo harmless"));
  frame(cmd("danger-two", "rm -rf ~/Documents"));
  return send;
}

describe("one gesture answers one card", () => {
  it("a double-click on Run answers the first card and never the one that moved up under the pointer", () => {
    const send = twoCommands();
    run();
    run();                                                           // the second click of the double-click: the next card's Run, same place
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "safe-one", scope: "once" }]]);
    expect(useArslanStore.getState().pendingCommands.map((c) => c.callId)).toEqual(["danger-two"]);
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("rm -rf ~/Documents");        // and it is still there, unanswered
  });

  it("two quick ⌘⏎ answer one card: the second press is not for the card that moved up", () => {
    const send = twoCommands();
    cmdKey({ metaKey: true });
    cmdKey({ metaKey: true });
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "safe-one", scope: "once" }]]);
    expect(useArslanStore.getState().pendingCommands.map((c) => c.callId)).toEqual(["danger-two"]);
  });

  it("a card resolved elsewhere, followed at once by a click, answers nothing: the click was meant for the one that left", () => {
    const send = twoCommands();
    frame({ type: "card_resolved", call_id: "safe-one", outcome: "approved", by: "phone" });
    run();
    cmdKey({ metaKey: true });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).not.toHaveBeenCalled();
    expect(useArslanStore.getState().pendingCommands.map((c) => c.callId)).toEqual(["danger-two"]);
  });

  it("a card that ran out, followed at once by a click, answers nothing either", () => {
    const send = twoCommands();
    act(() => { useArslanStore.getState().expireCard("safe-one"); });
    run();
    expect(send).not.toHaveBeenCalled();
  });

  it("a double-click on the only card does not answer the next one, proposed a moment later, that comes up under the pointer", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(cmd("safe-one", "echo harmless"));
    run();                                                           // the first click of the double-click: the slot is empty now
    advance(120);
    frame(cmd("danger-two", "rm -rf ~/Documents"));                  // the next command of the same turn, proposed as soon as the first one ran
    run();                                                           // the second click, on the card that came up under the pointer
    cmdKey({ metaKey: true });
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "safe-one", scope: "once" }]]);
    expect(useArslanStore.getState().pendingCommands.map((c) => c.callId)).toEqual(["danger-two"]);
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("rm -rf ~/Documents");
  });

  it("the card that comes up in the gap is held until 500 ms after the one that left, not 500 ms after it came up", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(cmd("safe-one", "echo harmless"));
    run();                                                           // t = 0: the card leaves
    advance(300);
    frame(cmd("danger-two", "rm -rf ~/Documents"));                  // t = 300
    advance(199);
    run();                                                           // t = 499: still held
    expect(send).toHaveBeenCalledTimes(1);
    advance(1);
    run();                                                           // t = 500: 200 ms after it came up, and the person has had the time
    expect(send.mock.calls.map(([f]) => f.call_id)).toEqual(["safe-one", "danger-two"]);
  });

  it("a card resolved on the phone leaves the same way: the next to come up within 500 ms is held", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(cmd("safe-one", "echo harmless"));
    frame({ type: "card_resolved", call_id: "safe-one", outcome: "approved", by: "phone" });
    advance(100);
    frame(cmd("danger-two", "rm -rf ~/Documents"));
    run();
    expect(send).not.toHaveBeenCalled();
    advance(400);
    run();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("a card that ran out leaves the same way, and a card that comes up right after is held", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(cmd("safe-one", "echo harmless"));
    act(() => { useArslanStore.getState().expireCard("safe-one"); });
    frame(cmd("danger-two", "rm -rf ~/Documents"));
    run();
    expect(send).not.toHaveBeenCalled();
  });

  it("500 ms later the next card answers normally; one millisecond short it does not", () => {
    const send = twoCommands();
    run();
    advance(499);
    run();
    expect(send).toHaveBeenCalledTimes(1);                           // 499 ms: still guarded
    advance(1);
    run();
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "safe-one", scope: "once" }],
                                           [{ type: "confirm_run_command", call_id: "danger-two", scope: "once" }]]);
  });

  it("a scope click on the card that moved up is ignored too: Always is not ticked unread", () => {
    twoCommands();
    run();
    fireEvent.click(screen.getByTestId("runcmd-scope-always"));
    expect((screen.getByTestId("runcmd-scope-always") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByTestId("runcmd-scope-once") as HTMLInputElement).checked).toBe(true);
    advance(500);
    fireEvent.click(screen.getByTestId("runcmd-scope-always"));
    expect((screen.getByTestId("runcmd-scope-always") as HTMLInputElement).checked).toBe(true);
  });

  it("a No, by its button or by Esc, aimed at the card that left is not a No to the one that moved up", () => {
    const send = twoCommands();
    run();
    fireEvent.click(screen.getByTestId("runcmd-cancel"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).toHaveBeenCalledTimes(1);
    expect(useArslanStore.getState().pendingCommands.map((c) => c.callId)).toEqual(["danger-two"]);
    advance(500);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).toHaveBeenLastCalledWith({ type: "cancel_run_command", call_id: "danger-two" });
  });

  it("the old card's tick ('don't ask again') is not ticked on the card that moved up either", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_run_command", call_id: "a", pretty: "ls a", reason: "" });          // old frames: the checkbox
    frame({ type: "propose_run_command", call_id: "b", pretty: "ls b", reason: "" });
    run();
    fireEvent.click(screen.getByTestId("runcmd-remember"));
    expect((screen.getByTestId("runcmd-remember") as HTMLInputElement).checked).toBe(false);
    advance(500);
    fireEvent.click(screen.getByTestId("runcmd-remember"));
    expect((screen.getByTestId("runcmd-remember") as HTMLInputElement).checked).toBe(true);
  });

  it("Esc in the composer right after a note answered a card is not a No to the card that moved up", () => {
    const send = vi.fn();
    render(<><AskSlot send={send} /><input id="chat-message-input" data-testid="composer" /></>);
    frame(cmd("safe-one", "echo harmless"));
    frame(cmd("danger-two", "rm -rf ~/Documents"));
    fireEvent.click(screen.getByTestId("runcmd-note-open"));
    fireEvent.change(screen.getByTestId("runcmd-note-input"), { target: { value: "no thanks" } });
    fireEvent.click(screen.getByTestId("runcmd-note-send"));
    expect(screen.getByTestId("composer")).toHaveFocus();
    fireEvent.keyDown(screen.getByTestId("composer"), { key: "Escape" });
    expect(send).toHaveBeenCalledTimes(1);                           // the note's own No, and nothing for danger-two
    advance(500);
    fireEvent.keyDown(screen.getByTestId("composer"), { key: "Escape" });
    expect(send).toHaveBeenLastCalledWith({ type: "cancel_run_command", call_id: "danger-two" });
  });
});

describe("what is not guarded", () => {
  it("a card that appears in an empty slot answers at once, and so does one that comes up after the slot has been empty for 500 ms", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(cmd("a", "ls a"));
    run();
    expect(send).toHaveBeenCalledTimes(1);
    advance(ANSWER_GUARD_MS);
    frame(cmd("b", "ls b"));                                           // the slot was empty for the whole time: a first card again
    run();
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("paging is not guarded, so a person can page through the cards as fast as they like", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("a", "ls a"));
    frame(cmd("b", "ls b"));
    frame(cmd("c", "ls c"));
    fireEvent.click(screen.getByLabelText("kit.next"));
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("ls c");
    fireEvent.click(screen.getByLabelText("kit.previous"));
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("ls b");
  });

  it("but the card paged to is guarded like any card that comes up: an answer within 500 ms is not for it", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(cmd("a", "ls a"));
    frame(cmd("b", "ls b"));
    fireEvent.click(screen.getByLabelText("kit.next"));
    run();
    expect(send).not.toHaveBeenCalled();
    advance(500);
    run();
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "b", scope: "once" });
  });

  it("the card on top sent again (a replay after a reconnect) is the same card: it does not start the guard again", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(cmd("a", "ls a"));
    frame(cmd("b", "ls b"));
    advance(5_000);
    frame(cmd("a", "ls a"));                                           // replayed: it is the newest now, but it is still the card the person is looking at
    run();
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "a", scope: "once" }]]);
  });
});

describe("no paging while the card on top is busy (F4)", () => {
  const card = (busy: boolean) => (
    <AskCard who="w" title="t" busy={busy} queue={{ index: 0, total: 2, onPrev: vi.fn(), onNext: vi.fn() }}
      onAllow={vi.fn()} onDecline={vi.fn()} />);

  it("‹ and › are disabled while the card's answer is in flight, and enabled when it is not", () => {
    const { rerender } = render(card(true));
    expect(screen.getByLabelText("kit.previous")).toBeDisabled();
    expect(screen.getByLabelText("kit.next")).toBeDisabled();
    rerender(card(false));
    expect(screen.getByLabelText("kit.previous")).toBeEnabled();
    expect(screen.getByLabelText("kit.next")).toBeEnabled();
  });

  it("an enroll-node card whose enrolment is in flight cannot be paged away from, and can be again if it failed", async () => {
    let fail: (e: Error) => void = () => {};
    vi.spyOn(client.api, "enrollSshNode").mockImplementation(() => new Promise((_ok, no) => { fail = no; }) as never);
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_enroll_node", call_id: "n1", name: "mini", host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] });
    frame({ type: "propose_enroll_node", call_id: "n2", name: "mac", host: "10.0.0.3", user: "me", fingerprints: ["SHA256:def"] });
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    expect(screen.getByLabelText("kit.next")).toBeDisabled();
    expect(screen.getByLabelText("kit.previous")).toBeDisabled();
    await act(async () => { fail(new Error("no route to host")); });
    expect(screen.getByLabelText("kit.next")).toBeEnabled();
    expect(screen.getByTestId("enroll-error")).toHaveTextContent("no route to host");
  });
});

describe("the guard outlives a re-render of whoever holds it", () => {
  it("a re-render of the chat while a card has just left does not make the slot forget it", () => {
    const send = vi.fn();
    const { rerender } = render(<AskSlot send={send} />);
    frame(cmd("a", "ls a"));
    run();                                                           // a leaves: the slot is empty
    rerender(<AskSlot send={send} />);                               // the chat re-renders (a streamed token, say)
    frame(cmd("b", "ls b"));
    run();
    expect(send).toHaveBeenCalledTimes(1);                           // b is still held
    advance(ANSWER_GUARD_MS);
    run();
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("a queue on its own (the Inbox's) keeps its guard across a re-render too", () => {
    const answered: string[] = [];
    const ask = (key: string) => ({ key, render: (queue: Parameters<Parameters<typeof AskQueue>[0]["items"][number]["render"]>[0]) => (
      <AskCard who="w" title={key} queue={queue} onAllow={() => answered.push(key)} onDecline={vi.fn()} />) });
    const { rerender } = render(<AskQueue items={[ask("a"), ask("b")]} />);
    rerender(<AskQueue items={[ask("b")]} />);                       // a left: b moved up
    fireEvent.click(screen.getByTestId("ask-allow"));
    expect(answered).toEqual([]);
    advance(ANSWER_GUARD_MS);
    fireEvent.click(screen.getByTestId("ask-allow"));
    expect(answered).toEqual(["b"]);
  });
});

describe("what the guard remembers", () => {
  it("a card that left holds the next one that comes up — now or in a moment — for 500 ms after it left, and no longer", () => {
    const guard = makeAnswerGuard();
    guard.shown("a");
    expect(guard.held()).toBe(false);                                // the first card of all
    guard.shown("a");
    expect(guard.held()).toBe(false);                                // the same card again is not a change
    guard.shown("b");                                                // a left: b moved up
    expect(guard.held()).toBe(true);
    advance(499);
    expect(guard.held()).toBe(true);
    advance(1);
    expect(guard.held()).toBe(false);
  });

  it("a card that left and none that came up still holds the one that comes up within 500 ms, from the moment it left", () => {
    const guard = makeAnswerGuard();
    guard.shown("a");
    guard.shown(null);                                               // t = 0: a left, the slot is empty
    advance(300);
    guard.shown("b");                                                // t = 300
    expect(guard.held()).toBe(true);
    advance(199);
    expect(guard.held()).toBe(true);                                 // t = 499
    advance(1);
    expect(guard.held()).toBe(false);                                // t = 500: from when a left, not from when b came up
  });

  it("the first card after the slot has been empty a while is not held", () => {
    const guard = makeAnswerGuard();
    guard.shown("a");
    guard.shown(null);
    advance(ANSWER_GUARD_MS);
    guard.shown("b");
    expect(guard.held()).toBe(false);
    guard.shown(null);                                               // an empty slot staying empty is not a card leaving
    advance(ANSWER_GUARD_MS);
    guard.shown(null);
    guard.shown("c");
    expect(guard.held()).toBe(false);
  });

  it("goes by a clock that never goes back: the system clock set an hour back or an hour on changes nothing", () => {
    const back = makeAnswerGuard();
    back.shown("a");
    back.shown("b");                                                 // a left
    vi.setSystemTime(Date.now() - 3_600_000);                        // the system corrects its clock an hour back
    expect(back.held()).toBe(true);
    advance(499);
    expect(back.held()).toBe(true);
    advance(1);
    expect(back.held()).toBe(false);                                 // 500 ms after a left, not an hour
    const on = makeAnswerGuard();
    on.shown("a");
    on.shown("b");
    vi.setSystemTime(Date.now() + 3_600_000);                        // the Mac wakes with its clock an hour on
    expect(on.held()).toBe(true);                                    // b is still not the person's to answer yet
  });

  it("each card that leaves starts the 500 ms again", () => {
    const guard = makeAnswerGuard();
    guard.shown("a");
    guard.shown("b");
    advance(400);
    guard.shown("c");                                                // b left at t = 400
    advance(400);
    expect(guard.held()).toBe(true);                                 // t = 800: 400 ms after b left
    advance(100);
    expect(guard.held()).toBe(false);
  });
});

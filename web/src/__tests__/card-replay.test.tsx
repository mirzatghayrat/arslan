/** 0.1.61 §A4 (PR 2b Task 4, carry N-M3; fix round 1, I2): a reconnect reconciles the shared cards. Every socket the server opens starts with the
 *  history frame and then replays the cards still waiting on the conversation (approvals.pending_cards: the SHARED ones — a command, a write, a
 *  schedule, an action). A card whose `card_resolved` was missed while the socket was down is not in that replay: it would sit in the slot as a
 *  dead "1 / 2" entry (an answer to it is swallowed) until its own expiry. But a replay that does not list a card does not say it is gone: a window's
 *  own card is private until the server sees its old socket close, and is not replayed though the server still waits on it. So after the history
 *  frame the window asks the server which cards wait (GET /approvals/pending: private and shared) and drops the stale cards of the four shared
 *  kinds that it does not list; the 3 s timer is only the fallback for a server that cannot be asked. Only those four kinds: the proposals that are
 *  never replayed (a machine to enrol) and the window's own capability card are left alone. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import * as client from "../api/client";
import AskSlot from "../components/AskSlot";
import { REPLAY_ASK_TIMEOUT_MS, REPLAY_SETTLE_MS, useArslanStore, initialArslanState } from "../stores/arslanStore";

/** What GET /approvals/pending answers: every card that still waits, shared or private, as the server lists them. */
let server: (() => Promise<unknown>) | null = null;
let asked: string[] = [];
let inits: (RequestInit | undefined)[] = [];
beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
  asked = [];
  inits = [];
  server = () => Promise.reject(new Error("the server cannot be asked"));          // by default: the timer's fallback
  vi.spyOn(client, "request").mockImplementation(((path: string, init?: RequestInit) => { asked.push(path); inits.push(init); return server!(); }) as never);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

const state = () => useArslanStore.getState();
const frame = (f: Record<string, unknown>) => act(() => { state().handleFrame(f as never); });
/** time passes, and what is waiting on a promise is let run */
const advance = (ms: number) => act(async () => { vi.advanceTimersByTime(ms); for (let i = 0; i < 20; i++) await Promise.resolve(); });
const answers = (...ids: string[]) => { server = () => Promise.resolve(ids.map((call_id) => ({ call_id, conversation_id: "main", frame: {} }))); };
const HISTORY = { type: "history", messages: [] };
const cmd = (id: string) => ({ type: "propose_run_command", call_id: id, pretty: `echo ${id}`, reason: "", options: ["once", "conversation"], perm_kind: "command" });
const action = (id: string) => ({ type: "propose_action", call_id: id, kind: "app", target: "Notes", detail: "", options: ["task", "conversation"], perm_kind: "app" });
const write = (id: string) => ({ type: "propose_workspace_write", call_id: id, workspace: "/w", action: "write_file", path: "a.md", options: ["once", "conversation"] });
const schedule = (id: string) => ({ type: "propose_schedule", call_id: id, name: "Brief", when: "every: 3600", options: ["once", "conversation"] });
const enroll = (id: string) => ({ type: "propose_enroll_node", call_id: id, name: "mini", host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] });
const capability = (id: string) => ({ type: "propose_capability", call_id: id, name: "Maps", tools: [], keys: [], folders: [] });
const waiting = () => [...state().pendingCommands, ...state().pendingActions, ...state().pendingWorkspaceWrites, ...state().pendingSchedules].map((c) => c.callId).sort();

describe("a reconnect drops the shared cards its replay no longer lists (the server cannot be asked: the timer is the fallback)", () => {
  it("what the replay lists stays; what it does not list goes, when the replay is over", async () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(action("a1")); frame(write("w1")); frame(schedule("s1"));
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('kit.queueOf:{"index":1,"total":4}');
    frame(HISTORY);                                            // the new socket's first frame ...
    frame(cmd("c1")); frame(write("w1"));                      // ... and the cards still waiting on the server
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c1", "w1"]);
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('kit.queueOf:{"index":1,"total":2}');
  });

  it("the card the person has open is not taken away the moment the socket is back: only when the replay is over", async () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    frame(cmd("c1"));
    await advance(REPLAY_SETTLE_MS - 1);
    expect(waiting()).toEqual(["a1", "c1"]);                   // still there, so a replay that is slow cannot make a live card flicker out
    await advance(1);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a replay that lists nothing clears every shared card, and says nothing about the person being away", async () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual([]);
    expect(state().cardExpired).toBe(false);                  // nobody knows these ran out: no “waiting for you” notice
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });

  it("the proposals that are never replayed, and the window's own capability card, are left alone", async () => {
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1")); frame(capability("k1")); frame(cmd("c1"));
    frame(HISTORY);
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual([]);
    expect(state().pendingEnrollNodes.map((c) => c.callId)).toEqual(["n1"]);
    expect(state().pendingCapabilities.map((c) => c.callId)).toEqual(["k1"]);
  });

  it("a card that arrives after the history and is not in the replay is a new one: it stays", async () => {
    frame(cmd("c1"));
    frame(HISTORY);
    frame(cmd("c2"));                                         // proposed live right after the reconnect
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c2"]);
  });

  it("a card the replay brings late is shown again, not lost", async () => {
    frame(cmd("c1"));
    frame(HISTORY);
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual([]);
    frame(cmd("c1"));                                         // a slow replay: the server did list it
    expect(waiting()).toEqual(["c1"]);
  });

  it("with no reconnect nothing is ever dropped, and a first history of an empty window sets nothing going", async () => {
    frame(HISTORY);
    expect(vi.getTimerCount()).toBe(0);
    expect(asked).toEqual([]);                                // nothing at stake: the server is not even asked
    frame(cmd("c1")); frame(action("a1"));
    await advance(REPLAY_SETTLE_MS * 10);
    expect(waiting()).toEqual(["a1", "c1"]);
  });

  it("a second history starts over: only what was shown then is at stake", async () => {
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    await advance(REPLAY_SETTLE_MS - 100);
    frame(action("a2"));                                      // arrives live before the first reconnect settles
    frame(HISTORY);                                           // the socket dropped again
    frame(cmd("c1")); frame(action("a2"));
    await advance(200);                                             // the first reconnect's time is up; the second's is not
    expect(waiting()).toEqual(["a1", "a2", "c1"]);
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["a2", "c1"]);                  // a1 was not in the second replay either
  });

  it("a new conversation cancels it: its cards are not touched by the old one's replay", async () => {
    frame(cmd("c1"));
    frame(HISTORY);
    expect(vi.getTimerCount()).toBe(2);                       // the reconnect is settling: its fallback timer, and the time the request is given
    act(() => { state().resetForNewConversation(); });
    expect(vi.getTimerCount()).toBe(0);                       // and the new conversation has put an end to it
    frame(cmd("c1"));                                         // the new conversation has a card with the same id
    await advance(REPLAY_SETTLE_MS * 2);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a store that is made new has no reconnect still settling", async () => {
    frame(cmd("c1"));
    frame(HISTORY);
    expect(vi.getTimerCount()).toBe(2);
    act(() => { useArslanStore.setState(initialArslanState(), true); });
    expect(vi.getTimerCount()).toBe(0);
    frame(cmd("c1"));
    await advance(REPLAY_SETTLE_MS * 2);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a card answered before the replay is over is simply gone; the reconciliation has nothing left to do for it", async () => {
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    act(() => { state().clearPendingAction("a1"); });
    frame(cmd("c1"));
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c1"]);
  });

  it("no dead “1 / 2” is left on screen: one card, no pager", async () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(cmd("c2"));
    expect(screen.getByTestId("ask-queue")).toBeInTheDocument();
    frame(HISTORY);
    frame(cmd("c2"));
    await advance(REPLAY_SETTLE_MS);
    expect(screen.queryByTestId("ask-queue")).toBeNull();
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("echo c2");
  });
});

describe("a reconnect asks the server which cards still wait, and drops exactly the ones that do not (fix round 1, I2)", () => {
  it("asks once, after the history frame, and not when nothing is on screen", async () => {
    frame(HISTORY);
    expect(asked).toEqual([]);
    frame(cmd("c1"));
    frame(HISTORY);
    expect(asked).toEqual(["/approvals/pending"]);
  });

  it("a card the server resolved is dropped as soon as it says so, without waiting for the timer; a card it still lists stays", async () => {
    frame(cmd("c1")); frame(action("a1")); frame(write("w1"));
    answers("c1", "w1");                                        // a1 was resolved while the socket was down
    frame(HISTORY);
    frame(cmd("c1")); frame(write("w1"));                       // the replay
    await advance(0);
    expect(waiting()).toEqual(["c1", "w1"]);
    expect(vi.getTimerCount()).toBe(0);                         // exact: no timer left to fire
  });

  it("a window's own private card that the server still waits on is never dropped, replayed or not (the half-open old socket)", async () => {
    frame(cmd("c1")); frame(action("a1"));
    answers("c1", "a1");                                        // c1 is private: pending_cards leaves it out, GET /approvals/pending lists it
    frame(HISTORY);
    frame(action("a1"));                                        // the replay lists the shared one only
    await advance(0);                                           // the server's list comes in (a long advance would run the timers before any answer could)
    await advance(REPLAY_SETTLE_MS * 10);
    expect(waiting()).toEqual(["a1", "c1"]);
  });

  it("the answer may come before the replay does: what the replay then lists is simply added again", async () => {
    frame(cmd("c1")); frame(action("a1"));
    answers("a1");
    frame(HISTORY);
    await advance(0);                                           // the server's list is in; the replay frames are not yet
    expect(waiting()).toEqual(["a1"]);
    frame(action("a1"));
    expect(waiting()).toEqual(["a1"]);
  });

  it("a server that lists nothing clears the stale cards at once; the proposals never replayed are left alone", async () => {
    frame(cmd("c1")); frame(enroll("n1")); frame(capability("k1"));
    answers();
    frame(HISTORY);
    await advance(0);
    expect(waiting()).toEqual([]);
    expect(state().pendingEnrollNodes.map((c) => c.callId)).toEqual(["n1"]);
    expect(state().pendingCapabilities.map((c) => c.callId)).toEqual(["k1"]);
    expect(state().cardExpired).toBe(false);
  });

  it("a card that arrived after the history is not at stake, whatever the server's list says", async () => {
    frame(cmd("c1"));
    answers();
    frame(HISTORY);
    frame(cmd("c2"));                                           // proposed live right after the reconnect, not yet in the list the server built
    await advance(0);
    expect(waiting()).toEqual(["c2"]);
  });

  it("a failed request falls back to the timer: the cards the replay does not list go when it is up, not before", async () => {
    frame(cmd("c1")); frame(action("a1"));
    server = () => Promise.reject(new Error("401"));
    frame(HISTORY);
    frame(cmd("c1"));
    await advance(REPLAY_SETTLE_MS - 1);
    expect(waiting()).toEqual(["a1", "c1"]);
    await advance(1);
    expect(waiting()).toEqual(["c1"]);
  });

  it("an answer that is no list is a failure too", async () => {
    frame(cmd("c1")); frame(action("a1"));
    server = () => Promise.resolve({ detail: "nope" });
    frame(HISTORY);
    frame(cmd("c1"));
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a slow request is waited for: the timer alone does not drop what the server may still list", async () => {
    frame(cmd("c1")); frame(action("a1"));
    let reply: (rows: unknown[]) => void = () => {};
    server = () => new Promise((ok) => { reply = ok; });
    frame(HISTORY);
    frame(cmd("c1"));
    await advance(REPLAY_ASK_TIMEOUT_MS - 1_000);
    expect(waiting()).toEqual(["a1", "c1"]);                    // still asked, not failed
    reply([{ call_id: "a1" }, { call_id: "c1" }]);
    await advance(0);
    expect(waiting()).toEqual(["a1", "c1"]);
  });

  it("the answer to an earlier reconnect does not touch the next one", async () => {
    frame(cmd("c1")); frame(action("a1"));
    let first: (rows: unknown[]) => void = () => {};
    server = () => new Promise((ok) => { first = ok; });
    frame(HISTORY);                                             // the first reconnect: a request is out
    server = () => Promise.reject(new Error("down"));
    frame(HISTORY);                                             // the socket dropped again
    frame(cmd("c1"));
    first([]);                                                  // the first request answers late, saying nothing waits
    await advance(0);
    expect(waiting()).toEqual(["a1", "c1"]);                    // not for it to say: it belongs to a reconnect that is over
    await advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c1"]);                          // the second one's fallback
  });

  it("a new conversation, or a new store, makes the answer that is still on its way count for nothing", async () => {
    frame(cmd("c1"));
    let reply: (rows: unknown[]) => void = () => {};
    server = () => new Promise((ok) => { reply = ok; });
    frame(HISTORY);
    act(() => { state().resetForNewConversation(); });
    frame(cmd("c1"));
    reply([]);
    await advance(0);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a request that never answers is given 10 s, then counts as a failure: the stale shared cards the replay did not list go, the ones it did stay", async () => {
    expect(REPLAY_ASK_TIMEOUT_MS).toBe(10_000);
    frame(cmd("c1")); frame(action("a1")); frame(write("w1"));
    server = () => new Promise(() => {});                       // the server never answers
    frame(HISTORY);
    frame(cmd("c1"));                                           // the replay lists c1 only
    await advance(REPLAY_SETTLE_MS + 1_000);                    // the fallback timer's time is long up: a request in flight does not trigger it
    expect(waiting()).toEqual(["a1", "c1", "w1"]);
    await advance(REPLAY_ASK_TIMEOUT_MS - REPLAY_SETTLE_MS - 1_000 - 100);   // 9.9 s
    expect(waiting()).toEqual(["a1", "c1", "w1"]);
    await advance(200);                                         // 10.1 s: given up
    expect(waiting()).toEqual(["c1"]);
    expect(vi.getTimerCount()).toBe(0);                         // nothing left to fire
    expect(state().cardExpired).toBe(false);
  });

  it("the request carries a signal, which is aborted when it is given up on (the fetch is not left running)", async () => {
    frame(cmd("c1")); frame(action("a1"));
    server = () => new Promise(() => {});
    frame(HISTORY);
    expect(inits).toHaveLength(1);
    const signal = inits[0]?.signal as AbortSignal;
    expect(signal).toBeInstanceOf(AbortSignal);
    await advance(REPLAY_ASK_TIMEOUT_MS - 100);
    expect(signal.aborted).toBe(false);
    await advance(200);
    expect(signal.aborted).toBe(true);
  });

  it("an answer inside the 10 s is exact as before, and the time given is not left running", async () => {
    frame(cmd("c1")); frame(action("a1"));
    let reply: (rows: unknown[]) => void = () => {};
    server = () => new Promise((ok) => { reply = ok; });
    frame(HISTORY);
    await advance(8_000);
    reply([{ call_id: "a1" }]);                                 // c1 is gone; a1 (private) still waits
    await advance(0);
    expect(waiting()).toEqual(["a1"]);
    expect(vi.getTimerCount()).toBe(0);
    await advance(REPLAY_ASK_TIMEOUT_MS * 2);
    expect(waiting()).toEqual(["a1"]);
  });

  it("an answer that comes after it was given up on changes nothing", async () => {
    frame(cmd("c1")); frame(action("a1"));
    let reply: (rows: unknown[]) => void = () => {};
    server = () => new Promise((ok) => { reply = ok; });
    frame(HISTORY);
    frame(cmd("c1"));
    await advance(REPLAY_ASK_TIMEOUT_MS + 100);
    expect(waiting()).toEqual(["c1"]);
    reply([{ call_id: "a1" }, { call_id: "c1" }]);              // too late: a1 is not brought back by a list
    await advance(0);
    expect(waiting()).toEqual(["c1"]);
  });
});

/** 0.1.61 §A4 (PR 2b Task 4, carry N-M3): a reconnect reconciles the shared cards. Every socket the server opens starts with the history
 *  frame and then replays the cards still waiting on the conversation (approvals.pending_cards: the shared ones — a command, a write, a
 *  schedule, an action). A card whose `card_resolved` was missed while the socket was down is not in that replay: it would sit in the
 *  slot as a dead "1 / 2" entry (an answer to it is swallowed) until its own expiry. So the cards the replay does not list are dropped
 *  once it is over — and only those four kinds; the proposals that are never replayed (a machine to enrol, a server to connect) and the
 *  window's own capability card are left alone. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { REPLAY_SETTLE_MS, useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

const state = () => useArslanStore.getState();
const frame = (f: Record<string, unknown>) => act(() => { state().handleFrame(f as never); });
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const HISTORY = { type: "history", messages: [] };
const cmd = (id: string) => ({ type: "propose_run_command", call_id: id, pretty: `echo ${id}`, reason: "", options: ["once", "conversation"], perm_kind: "command" });
const action = (id: string) => ({ type: "propose_action", call_id: id, kind: "app", target: "Notes", detail: "", options: ["task", "conversation"], perm_kind: "app" });
const write = (id: string) => ({ type: "propose_workspace_write", call_id: id, workspace: "/w", action: "write_file", path: "a.md", options: ["once", "conversation"] });
const schedule = (id: string) => ({ type: "propose_schedule", call_id: id, name: "Brief", when: "every: 3600", options: ["once", "conversation"] });
const enroll = (id: string) => ({ type: "propose_enroll_node", call_id: id, name: "mini", host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] });
const connect = (id: string) => ({ type: "propose_connect_mcp", call_id: id, key: "memory", label: "Memory", transport: "stdio", command: "npx",
  argv: [], url: null, env_keys: [], prerequisites: "", requires_path: false, path_placeholder: null });
const capability = (id: string) => ({ type: "propose_capability", call_id: id, name: "Maps", tools: [], keys: [], folders: [] });
const waiting = () => [...state().pendingCommands, ...state().pendingActions, ...state().pendingWorkspaceWrites, ...state().pendingSchedules].map((c) => c.callId).sort();

describe("a reconnect drops the shared cards its replay no longer lists", () => {
  it("what the replay lists stays; what it does not list goes, when the replay is over", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(action("a1")); frame(write("w1")); frame(schedule("s1"));
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('kit.queueOf:{"index":1,"total":4}');
    frame(HISTORY);                                            // the new socket's first frame ...
    frame(cmd("c1")); frame(write("w1"));                      // ... and the cards still waiting on the server
    advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c1", "w1"]);
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('kit.queueOf:{"index":1,"total":2}');
  });

  it("the card the person has open is not taken away the moment the socket is back: only when the replay is over", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    frame(cmd("c1"));
    advance(REPLAY_SETTLE_MS - 1);
    expect(waiting()).toEqual(["a1", "c1"]);                   // still there, so a replay that is slow cannot make a live card flicker out
    advance(1);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a replay that lists nothing clears every shared card, and says nothing about the person being away", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual([]);
    expect(state().cardExpired).toBe(false);                  // nobody knows these ran out: no “waiting for you” notice
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });

  it("the proposals that are never replayed, and the window's own capability card, are left alone", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1")); frame(connect("m1")); frame(capability("k1")); frame(cmd("c1"));
    frame(HISTORY);
    advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual([]);
    expect(state().pendingEnrollNodes.map((c) => c.callId)).toEqual(["n1"]);
    expect(state().pendingConnectMcps.map((c) => c.callId)).toEqual(["m1"]);
    expect(state().pendingCapabilities.map((c) => c.callId)).toEqual(["k1"]);
  });

  it("a card that arrives after the history and is not in the replay is a new one: it stays", () => {
    frame(cmd("c1"));
    frame(HISTORY);
    frame(cmd("c2"));                                         // proposed live right after the reconnect
    advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c2"]);
  });

  it("a card the replay brings late is shown again, not lost", () => {
    frame(cmd("c1"));
    frame(HISTORY);
    advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual([]);
    frame(cmd("c1"));                                         // a slow replay: the server did list it
    expect(waiting()).toEqual(["c1"]);
  });

  it("with no reconnect nothing is ever dropped, and a first history of an empty window sets nothing going", () => {
    frame(HISTORY);
    expect(vi.getTimerCount()).toBe(0);
    frame(cmd("c1")); frame(action("a1"));
    advance(REPLAY_SETTLE_MS * 10);
    expect(waiting()).toEqual(["a1", "c1"]);
  });

  it("a second history starts over: only what was shown then is at stake", () => {
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    advance(REPLAY_SETTLE_MS - 100);
    frame(action("a2"));                                      // arrives live before the first reconnect settles
    frame(HISTORY);                                           // the socket dropped again
    frame(cmd("c1")); frame(action("a2"));
    advance(200);                                             // the first reconnect's time is up; the second's is not
    expect(waiting()).toEqual(["a1", "a2", "c1"]);
    advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["a2", "c1"]);                  // a1 was not in the second replay either
  });

  it("a new conversation cancels it: its cards are not touched by the old one's replay", () => {
    frame(cmd("c1"));
    frame(HISTORY);
    expect(vi.getTimerCount()).toBe(1);                       // the reconnect is settling
    act(() => { state().resetForNewConversation(); });
    expect(vi.getTimerCount()).toBe(0);                       // and the new conversation has put an end to it
    frame(cmd("c1"));                                         // the new conversation has a card with the same id
    advance(REPLAY_SETTLE_MS * 2);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a store that is made new has no reconnect still settling", () => {
    frame(cmd("c1"));
    frame(HISTORY);
    expect(vi.getTimerCount()).toBe(1);
    act(() => { useArslanStore.setState(initialArslanState(), true); });
    expect(vi.getTimerCount()).toBe(0);
    frame(cmd("c1"));
    advance(REPLAY_SETTLE_MS * 2);
    expect(waiting()).toEqual(["c1"]);
  });

  it("a card answered before the replay is over is simply gone; the reconciliation has nothing left to do for it", () => {
    frame(cmd("c1")); frame(action("a1"));
    frame(HISTORY);
    act(() => { state().clearPendingAction("a1"); });
    frame(cmd("c1"));
    advance(REPLAY_SETTLE_MS);
    expect(waiting()).toEqual(["c1"]);
  });

  it("no dead “1 / 2” is left on screen: one card, no pager", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(cmd("c2"));
    expect(screen.getByTestId("ask-queue")).toBeInTheDocument();
    frame(HISTORY);
    frame(cmd("c2"));
    advance(REPLAY_SETTLE_MS);
    expect(screen.queryByTestId("ask-queue")).toBeNull();
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("echo c2");
  });
});

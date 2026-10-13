/** 0.1.61 §A4 (PR 2b Task 3, fix round 3, G2): an apply in flight never blocks the queue. Connecting a server and enrolling a machine call
 *  the REST API from the card and take a while (a hung one has no client timeout). Whether the apply is in flight, and how it ended, is
 *  the store's, by call id — not the card's: the card is remounted when the person pages away and back. While it is in flight that card's
 *  own buttons stay off (never a second apply), but paging and every other card stay available; when it ends the card answers again. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import * as client from "../api/client";
import * as mcpApi from "../api/mcp";
import AskSlot from "../components/AskSlot";
import { ANSWER_GUARD_MS } from "../components/kit";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

const state = () => useArslanStore.getState();
const frame = (f: Record<string, unknown>) => act(() => { state().handleFrame(f as never); });
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
/** the card on top changed: it answers once the answer guard has run out */
const settle = () => advance(ANSWER_GUARD_MS);
/** let the promise chain of an apply run to its end */
const flush = () => act(async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); });
const cmd = (id: string, pretty: string) => ({ type: "propose_run_command", call_id: id, pretty, reason: "", options: ["once", "conversation"], perm_kind: "command" });
const connect = (id: string) => ({ type: "propose_connect_mcp", call_id: id, key: "memory", label: `Memory ${id}`, transport: "stdio", command: "npx",
  argv: [], url: null, env_keys: [], prerequisites: "", requires_path: false, path_placeholder: null });
const enroll = (id: string) => ({ type: "propose_enroll_node", call_id: id, name: `mini-${id}`, host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] });
const next = () => fireEvent.click(screen.getByLabelText("kit.next"));
const prev = () => fireEvent.click(screen.getByLabelText("kit.previous"));

/** a connect whose first REST call never answers until the test says so */
function hungConnect() {
  let release: (server: { id: number }) => void = () => {};
  let fail: (e: Error) => void = () => {};
  const add = vi.spyOn(mcpApi, "addMcpServer").mockImplementation(() => new Promise((ok, no) => { release = ok as never; fail = no; }) as never);
  vi.spyOn(mcpApi, "connectMcpServer").mockResolvedValue([{ key: "mcp_7__list", name: "list", suggested_tier: "safe" }] as never);
  vi.spyOn(mcpApi, "exposeMcpServer").mockResolvedValue({ ok: true } as never);
  vi.spyOn(mcpApi, "wireMcpTool").mockResolvedValue({ ok: true } as never);
  return { add, release: () => release({ id: 7 }), fail: () => fail(new Error("no")) };
}
/** a command card first, the connect card behind it (proposals to connect wait behind every ask); the connect card is on screen and Connect is pressed */
function connectInFlight(send = vi.fn()) {
  const hung = hungConnect();
  render(<AskSlot send={send} />);
  frame(cmd("c1", "ls a"));
  frame(connect("m1"));
  next();
  settle();
  fireEvent.click(screen.getByTestId("connect-mcp-connect"));
  return { hung, send };
}

describe("a connect in flight never blocks the queue", () => {
  it("paging stays available, and the command card behind it is answered", () => {
    const { hung, send } = connectInFlight();
    expect(hung.add).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("connect-mcp-connect")).toBeDisabled();             // its own buttons are off ...
    expect(screen.getByLabelText("kit.previous")).toBeEnabled();                   // ... paging is not
    expect(screen.getByLabelText("kit.next")).toBeEnabled();
    prev();
    settle();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "c1", scope: "once" }]]);
    expect(state().pendingCommands).toEqual([]);
    expect(state().pendingConnectMcps.map((c) => c.callId)).toEqual(["m1"]);        // and the connect card waits on
  });

  it("paged back to, it is still busy: Connect stays off, and no click or key starts a second apply", () => {
    const { hung } = connectInFlight();
    prev();
    expect(screen.getByTestId("runcmd-card")).toBeInTheDocument();                 // really paged away: the connect card is gone from the screen
    expect(screen.queryByTestId("connect-mcp-card")).toBeNull();
    settle();
    next();
    expect(screen.getByTestId("connect-mcp-card")).toBeInTheDocument();            // and back: a card mounted anew
    settle();
    const button = screen.getByTestId("connect-mcp-connect");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("connectionsUI.connecting");
    fireEvent.click(button);
    fireEvent.click(screen.getByTestId("connect-mcp-cancel"));
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(hung.add).toHaveBeenCalledTimes(1);
    expect(state().pendingConnectMcps.map((c) => c.callId)).toEqual(["m1"]);        // Cancel did not take it away either
  });

  it("a second Connect before the first has answered starts nothing", () => {
    const { hung } = connectInFlight();
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    expect(hung.add).toHaveBeenCalledTimes(1);
  });

  it("nor does a second click that comes before the card has been drawn busy: the handler asks the store, not the render", () => {
    const hung = hungConnect();
    render(<AskSlot send={vi.fn()} />);
    frame(connect("m1"));
    settle();
    const button = screen.getByTestId("connect-mcp-connect");
    act(() => { button.click(); button.click(); });                                // both before React re-renders: the button is still enabled for the second
    expect(hung.add).toHaveBeenCalledTimes(1);
  });

  it("is still busy after the chat is left and come back to (the slot is mounted again)", () => {
    const { hung } = connectInFlight();
    cleanup();                                                                     // the person goes to another section: the slot unmounts
    render(<AskSlot send={vi.fn()} />);                                            // and back
    next();
    settle();
    expect(screen.getByTestId("connect-mcp-connect")).toBeDisabled();
    expect(hung.add).toHaveBeenCalledTimes(1);
  });

  it("when the apply fails the card answers again, and says why, also when it failed while the card was paged away", async () => {
    const { hung } = connectInFlight();
    prev();
    expect(screen.queryByTestId("connect-mcp-card")).toBeNull();
    settle();
    await act(async () => { hung.fail(); });                                       // it fails while the command card is on screen
    next();
    settle();
    expect(screen.getByTestId("connect-mcp-connect")).toBeEnabled();
    expect(screen.getByText("connectionsUI.failed_add")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));                   // a retry is a new apply, and the old failure is gone
    expect(hung.add).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("connectionsUI.failed_add")).toBeNull();
    expect(screen.getByTestId("connect-mcp-connect")).toBeDisabled();
  });

  it("an apply chain that throws instead of answering does not leave the card busy for good", async () => {
    const { hung } = connectInFlight();
    // the chain's last line reads tools.length outside its try: a response whose length throws makes the whole chain throw
    vi.mocked(mcpApi.connectMcpServer).mockResolvedValue({ [Symbol.iterator]: function* () { /* no tools */ }, get length(): number { throw new Error("boom"); } } as never);
    await act(async () => { hung.release(); });
    await flush();
    expect(state().cardApply.m1.busy).toBe(false);
    expect(screen.getByTestId("connect-mcp-connect")).toBeEnabled();
    expect(screen.getByText("connectionsUI.error")).toBeInTheDocument();             // no stage: the generic failure
  });

  it("when the apply fails while the card is on screen it answers again at once", async () => {
    const { hung } = connectInFlight();
    await act(async () => { hung.fail(); });
    expect(screen.getByTestId("connect-mcp-connect")).toBeEnabled();
    expect(screen.getByTestId("connect-mcp-cancel")).toBeEnabled();
    expect(screen.getByText("connectionsUI.failed_add")).toBeInTheDocument();
  });

  it("an apply that succeeds while the card is paged away: the server is told, and paged back the card shows it connected and applies nothing twice", async () => {
    const { hung, send } = connectInFlight();
    prev();
    expect(screen.queryByTestId("connect-mcp-card")).toBeNull();
    settle();
    hung.release();
    await flush();
    expect(send).toHaveBeenCalledWith({ type: "confirm_connect_mcp", call_id: "m1", server_id: 7, tool_count: 1 });
    expect(state().pendingConnectMcps[0].appliedServerId).toBe(7);
    next();
    settle();
    expect(screen.getByText('connectionsUI.ready:{"safe":1,"restricted":0}')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(hung.add).toHaveBeenCalledTimes(1);
  });
});

describe("an enrolment in flight never blocks the queue either", () => {
  /** an enrolment that never answers until the test says so; the enroll card first, a command card behind it */
  function enrolInFlight(send = vi.fn()) {
    let fail: (e: Error) => void = () => {};
    let done: () => void = () => {};
    const spy = vi.spyOn(client.api, "enrollSshNode").mockImplementation(() => new Promise((ok, no) => { done = () => ok({} as never); fail = no; }) as never);
    render(<AskSlot send={send} />);
    frame(enroll("n1"));
    frame(cmd("c1", "ls a"));
    settle();                                                                      // the enroll card came up where none was
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    return { spy, send, fail: (m = "no route to host") => fail(new Error(m)), done: () => done() };
  }

  it("paging stays available and the command card is answered; paged back the enrolment is still busy", () => {
    const { spy, send } = enrolInFlight();
    expect(screen.getByTestId("enroll-confirm")).toBeDisabled();
    expect(screen.getByLabelText("kit.next")).toBeEnabled();
    next();
    settle();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "c1", scope: "once" }]]);
    settle();                                                                      // the enroll card is back on top
    const button = screen.getByTestId("enroll-confirm");
    expect(button).toBeDisabled();
    fireEvent.click(button);
    fireEvent.click(screen.getByTestId("enroll-cancel"));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(state().pendingEnrollNodes.map((c) => c.callId)).toEqual(["n1"]);
  });

  it("when the enrolment fails the card answers again with the reason, also when it failed while the card was paged away", async () => {
    const { spy, fail } = enrolInFlight();
    next();
    expect(screen.queryByTestId("enroll-node-card")).toBeNull();
    settle();
    await act(async () => { fail("that machine is presenting a different host key"); });
    prev();
    settle();
    expect(screen.getByTestId("enroll-error")).toHaveTextContent("that machine is presenting a different host key");
    expect(screen.getByTestId("enroll-confirm")).toBeEnabled();
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    expect(spy).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("enroll-error")).toBeNull();
  });

  it("when the enrolment worked the card leaves", async () => {
    const { done } = enrolInFlight();
    await act(async () => { done(); });
    expect(state().pendingEnrollNodes).toEqual([]);
    expect(screen.queryByTestId("enroll-node-card")).toBeNull();
  });

  it("a second click before the card has been drawn busy starts no second enrolment", () => {
    const spy = vi.spyOn(client.api, "enrollSshNode").mockImplementation(() => new Promise(() => {}) as never);
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    settle();
    const button = screen.getByTestId("enroll-confirm");
    act(() => { button.click(); button.click(); });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("an enrolment that worked is not left busy, even when whoever hears of it does not take the card away", async () => {
    vi.spyOn(client.api, "enrollSshNode").mockResolvedValue({} as never);
    const onDone = vi.fn();
    const { default: EnrollNodeCard } = await import("../components/EnrollNodeCard");
    render(<EnrollNodeCard callId="n9" name="mini" host="10.0.0.2" user="me" fingerprints={["SHA256:abc"]} onDone={onDone} />);
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    await flush();
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(state().cardApply.n9).toEqual({ busy: false });
    expect(screen.getByTestId("enroll-confirm")).toBeEnabled();
  });
});

describe("the store keeps an apply by call id, and lets go of it with the card", () => {
  it("begins busy, ends with its outcome, and a new apply forgets the last outcome", () => {
    state().beginCardApply("m1");
    expect(state().cardApply).toEqual({ m1: { busy: true } });
    state().endCardApply("m1", { error: "x" });
    expect(state().cardApply).toEqual({ m1: { busy: false, error: "x" } });
    state().beginCardApply("m1");
    expect(state().cardApply).toEqual({ m1: { busy: true } });
    state().endCardApply("m1");
    expect(state().cardApply).toEqual({ m1: { busy: false } });
  });

  it("two cards' applies are two entries: ending one leaves the other busy", () => {
    state().beginCardApply("m1");
    state().beginCardApply("n1");
    state().endCardApply("m1");
    expect(state().cardApply.m1.busy).toBe(false);
    expect(state().cardApply.n1.busy).toBe(true);
  });

  it("an apply that ends after its card is gone leaves nothing behind", () => {
    state().endCardApply("gone", { error: "x" });
    expect(state().cardApply).toEqual({});
  });

  it.each([
    ["the connect card is cancelled", () => { frame(connect("m1")); state().beginCardApply("m1"); act(() => state().clearPendingConnectMcp("m1")); }],
    ["the enroll card is done", () => { frame(enroll("m1")); state().beginCardApply("m1"); act(() => state().clearPendingEnrollNode("m1")); }],
    ["the card is resolved elsewhere", () => { frame(connect("m1")); state().beginCardApply("m1"); frame({ type: "card_resolved", call_id: "m1", outcome: "approved", by: "phone" }); }],
    ["the card runs out", () => { frame(connect("m1")); state().beginCardApply("m1"); act(() => state().expireCard("m1")); }],
    ["its follow-up names it", () => { frame(connect("m1")); state().beginCardApply("m1");
      frame({ type: "mcp_connect_followup", call_id: "m1", server_id: 7, tool_count: 1, safe_count: 1, restricted_count: 0, assignable: true }); }],
    ["its follow-up names its server", () => { frame(connect("m1")); act(() => state().markConnectApplied("m1", 7)); state().beginCardApply("m1");
      frame({ type: "mcp_connect_followup", server_id: 7, tool_count: 1, safe_count: 1, restricted_count: 0, assignable: true }); }],
    ["a new conversation begins", () => { frame(connect("m1")); state().beginCardApply("m1"); act(() => state().resetForNewConversation()); }],
  ])("the entry goes when %s", (_name, leave) => {
    leave();
    expect(state().cardApply).toEqual({});
  });

  it("but not another card's: a card leaving takes its own entry only", () => {
    frame(connect("m1"));
    frame(connect("m2"));
    state().beginCardApply("m1");
    state().beginCardApply("m2");
    act(() => state().clearPendingConnectMcp("m1"));
    expect(Object.keys(state().cardApply)).toEqual(["m2"]);
  });
});

/** 0.1.61 §A4 (PR 2b Task 4, carry from Task 3): a card whose apply is in flight (connecting a server, enrolling a machine) turns its own
 *  buttons off, and a REST call has no client timeout, so a hung apply used to hold its card in the slot until the apply settled. While it
 *  is in flight the card offers "Hide": the apply goes on, the card leaves (the next one moves up), and when it settles the chat says how
 *  it ended. Nothing else can be hidden, and a card nobody hid shows its own outcome and adds nothing to the chat. */
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
const flush = () => act(async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); });
const notes = () => state().items.filter((i) => i.kind === "system").map((i) => i.content);
const cmd = (id: string) => ({ type: "propose_run_command", call_id: id, pretty: `echo ${id}`, reason: "", options: ["once", "conversation"], perm_kind: "command" });
const connect = (id: string) => ({ type: "propose_connect_mcp", call_id: id, key: "memory", label: `Memory ${id}`, transport: "stdio", command: "npx",
  argv: [], url: null, env_keys: [], prerequisites: "", requires_path: false, path_placeholder: null });
const enroll = (id: string) => ({ type: "propose_enroll_node", call_id: id, name: `mini-${id}`, host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] });

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
/** an enrolment that never answers until the test says so */
function hungEnroll() {
  let release: () => void = () => {};
  let fail: (e: unknown) => void = () => {};
  const call = vi.spyOn(client.api, "enrollSshNode").mockImplementation(() => new Promise((ok, no) => { release = ok as never; fail = no; }) as never);
  return { call, release: () => release(), fail: (e: unknown) => fail(e) };
}

describe("Hide is the way out of a card whose apply is in flight", () => {
  it("is offered only once the apply is in flight, and goes when it has ended", async () => {
    const hung = hungConnect();
    render(<AskSlot send={vi.fn()} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    expect(screen.queryByTestId("connect-mcp-hide")).toBeNull();
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    expect(screen.getByTestId("connect-mcp-hide")).toHaveTextContent("kit.hide");
    expect(screen.getByTestId("connect-mcp-card")).toHaveTextContent("kit.hideHint");
    hung.release();
    await flush();
    expect(screen.queryByTestId("connect-mcp-hide")).toBeNull();
  });

  it("hiding takes the card out of the slot; the apply goes on, once", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    expect(screen.queryByTestId("connect-mcp-card")).toBeNull();
    expect(state().pendingConnectMcps).toEqual([]);
    expect(state().cardApply.m1).toEqual({ busy: true, hidden: true });
    expect(hung.add).toHaveBeenCalledTimes(1);
    await flush();
    expect(send).not.toHaveBeenCalled();                              // nothing was answered by hiding
  });

  it("the card behind it moves up", () => {
    hungConnect();
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1")); frame(connect("m1"));
    fireEvent.click(screen.getByLabelText("kit.next"));
    advance(ANSWER_GUARD_MS);
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    expect(screen.queryByTestId("connect-mcp-card")).toBeNull();
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("echo c1");
    expect(screen.queryByTestId("ask-queue")).toBeNull();
  });

  it("a card that is not busy cannot be hidden, and neither can one that is not there", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(connect("m1")); frame(enroll("n1")); frame(cmd("c1"));
    act(() => { state().hideCard("m1"); state().hideCard("n1"); state().hideCard("c1"); state().hideCard("nope"); });
    expect(state().pendingConnectMcps.map((c) => c.callId)).toEqual(["m1"]);
    expect(state().pendingEnrollNodes.map((c) => c.callId)).toEqual(["n1"]);
    expect(state().pendingCommands.map((c) => c.callId)).toEqual(["c1"]);
    expect(state().cardApply).toEqual({});
  });

  it("nor one whose apply has ended (it shows how, and can be tried again)", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    act(() => { state().beginCardApply("n1"); state().endCardApply("n1", { error: "host key mismatch" }); state().hideCard("n1"); });
    expect(state().pendingEnrollNodes.map((c) => c.callId)).toEqual(["n1"]);
    expect(state().cardApply.n1).toEqual({ busy: false, error: "host key mismatch" });
  });

  it("an answer card has no Hide: it has nothing in flight", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(cmd("c1"));
    expect(screen.queryByText("kit.hide")).toBeNull();
  });
});

describe("when a hidden connect settles, the chat says how it ended", () => {
  it("it connected: a note names the server, and the server is still told (so its follow-up comes)", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    expect(notes()).toEqual([]);
    hung.release();
    await flush();
    expect(notes()).toEqual(['kit.hiddenConnected:{"name":"Memory m1"}']);
    expect(send).toHaveBeenCalledWith({ type: "confirm_connect_mcp", call_id: "m1", server_id: 7, tool_count: 1 });
    expect(state().cardApply).toEqual({});                             // nothing is kept for a card that has gone
  });

  it("it failed: a note names the server and where it stopped, and the server is not told it connected", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    hung.fail();
    await flush();
    expect(notes()).toEqual(['kit.hiddenConnectFailed:{"name":"Memory m1","why":"connectionsUI.failed_add"}']);
    expect(send).not.toHaveBeenCalled();
    expect(state().cardApply).toEqual({});
  });

  it("a card nobody hid shows its own outcome and adds nothing to the chat", async () => {
    const hung = hungConnect();
    render(<AskSlot send={vi.fn()} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    hung.release();
    await flush();
    expect(notes()).toEqual([]);
    expect(screen.getByTestId("connect-mcp-card")).toHaveTextContent("connectionsUI.ready");
  });

  it("if the person has moved to another conversation by then, nothing is said into it", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    act(() => { state().resetForNewConversation(); });
    hung.release();
    await flush();
    expect(notes()).toEqual([]);
  });
});

describe("a proposal that is delivered again while its apply is hidden does not bring the card back", () => {
  // A proposal is journaled and replayed to a socket that re-attaches (ws/arslan.py): a reconnect during a hung hidden apply delivers it again.
  it("a connect: the card stays gone, the apply is not started twice, and when it settles the chat says so", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    frame(connect("m1"));                                              // the journal replays the proposal
    expect(screen.queryByTestId("connect-mcp-card")).toBeNull();
    expect(state().pendingConnectMcps).toEqual([]);
    hung.release();
    await flush();
    expect(screen.queryByTestId("connect-mcp-card")).toBeNull();      // and it is not there with Connect live once the apply has settled
    expect(hung.add).toHaveBeenCalledTimes(1);
    expect(notes()).toEqual(['kit.hiddenConnected:{"name":"Memory m1"}']);
  });

  it("an enrolment: the same", async () => {
    const hung = hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    fireEvent.click(screen.getByTestId("enroll-hide"));
    frame(enroll("n1"));
    expect(screen.queryByTestId("enroll-node-card")).toBeNull();
    hung.release();
    await flush();
    expect(screen.queryByTestId("enroll-node-card")).toBeNull();
    expect(hung.call).toHaveBeenCalledTimes(1);
  });

  it("a card whose apply is in flight but not hidden is shown again, busy, as before", () => {
    hungConnect();
    render(<AskSlot send={vi.fn()} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    frame(connect("m1"));
    expect(screen.getByTestId("connect-mcp-card")).toBeInTheDocument();
    expect(screen.getByTestId("connect-mcp-connect")).toBeDisabled();
  });

  it("a proposal with another id is a new card, hidden apply or not", () => {
    hungConnect();
    render(<AskSlot send={vi.fn()} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    frame(connect("m2"));
    expect(state().pendingConnectMcps.map((c) => c.callId)).toEqual(["m2"]);
  });
});

describe("an apply that settles in another conversation tells nobody there", () => {
  it("a hidden connect: no confirm_connect_mcp goes to the new conversation's socket, and no note is added to its chat", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    fireEvent.click(screen.getByTestId("connect-mcp-hide"));
    act(() => { state().resetForNewConversation(); });
    hung.release();
    await flush();
    expect(send).not.toHaveBeenCalled();
    expect(notes()).toEqual([]);
  });

  it("a connect nobody hid: the same", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    act(() => { state().resetForNewConversation(); });
    hung.release();
    await flush();
    expect(send).not.toHaveBeenCalled();
  });

  it("in the same conversation it still tells the server, as before", async () => {
    const hung = hungConnect();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(connect("m1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("connect-mcp-connect"));
    hung.release();
    await flush();
    expect(send).toHaveBeenCalledWith({ type: "confirm_connect_mcp", call_id: "m1", server_id: 7, tool_count: 1 });
  });

  it("a hidden enrolment: no note is added to the new conversation's chat (its entry went with the old one)", async () => {
    const hung = hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    fireEvent.click(screen.getByTestId("enroll-hide"));
    act(() => { state().resetForNewConversation(); });
    hung.release();
    await flush();
    expect(notes()).toEqual([]);
  });

  it("each new conversation counts: the epoch only goes up", () => {
    const before = state().epoch;
    act(() => { state().resetForNewConversation(); state().resetForNewConversation(); });
    expect(state().epoch).toBe(before + 2);
  });
});

describe("when a hidden enrolment settles, the chat says how it ended", () => {
  it("it worked: a note names the machine", async () => {
    const hung = hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    expect(screen.queryByTestId("enroll-hide")).toBeNull();                 // nothing in flight yet
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    expect(screen.getByTestId("enroll-hide")).toHaveTextContent("kit.hide");
    fireEvent.click(screen.getByTestId("enroll-hide"));
    expect(screen.queryByTestId("enroll-node-card")).toBeNull();
    expect(hung.call).toHaveBeenCalledTimes(1);
    hung.release();
    await flush();
    expect(notes()).toEqual(['kit.hiddenEnrolled:{"name":"mini-n1"}']);
    expect(state().cardApply).toEqual({});
    expect(state().pendingEnrollNodes).toEqual([]);
  });

  it("it failed: a note names the machine and says why", async () => {
    const hung = hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    fireEvent.click(screen.getByTestId("enroll-hide"));
    hung.fail(new Error("host key mismatch"));
    await flush();
    expect(notes()).toEqual(['kit.hiddenEnrollFailed:{"name":"mini-n1","why":"host key mismatch"}']);
  });

  it("it failed with no reason in words: the app's own line says so", async () => {
    const hung = hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    fireEvent.click(screen.getByTestId("enroll-hide"));
    hung.fail("boom");
    await flush();
    expect(notes()).toEqual(['kit.hiddenEnrollFailed:{"name":"mini-n1","why":"enroll.failed"}']);
  });

  it("a card nobody hid shows its own error and adds nothing to the chat", async () => {
    const hung = hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    hung.fail(new Error("host key mismatch"));
    await flush();
    expect(notes()).toEqual([]);
    expect(screen.getByTestId("enroll-error")).toHaveTextContent("host key mismatch");
  });
});

describe("the words", () => {
  it("every language has Hide, its hint and the four ways a hidden apply ends, each naming the thing", async () => {
    const files = await Promise.all(["en", "zh", "ja", "es", "de", "fr"].map(async (l) => [l, (await import(`../locales/${l}.json`)).default.kit] as const));
    for (const [lang, kit] of files) {
      for (const key of ["hide", "hideHint", "hiddenConnected", "hiddenConnectFailed", "hiddenEnrolled", "hiddenEnrollFailed"]) {
        expect(kit[key], `${lang} kit.${key}`).toBeTypeOf("string");
        expect(kit[key].trim().length, `${lang} kit.${key}`).toBeGreaterThan(0);
      }
      for (const key of ["hiddenConnected", "hiddenConnectFailed", "hiddenEnrolled", "hiddenEnrollFailed"]) expect(kit[key], `${lang} kit.${key}`).toContain("{{name}}");
      for (const key of ["hiddenConnectFailed", "hiddenEnrollFailed"]) expect(kit[key], `${lang} kit.${key}`).toContain("{{why}}");
    }
  });
});

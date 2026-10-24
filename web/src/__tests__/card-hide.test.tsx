/** 0.1.61 §A4 (PR 2b Task 4, carry from Task 3): a card whose apply is in flight (enrolling a machine; connecting a server was the other
 *  until 0.1.63 C9b removed that card) turns its own
 *  buttons off, and a REST call has no client timeout, so a hung apply used to hold its card in the slot until the apply settled. While it
 *  is in flight the card offers "Hide": the apply goes on, the card leaves (the next one moves up), and when it settles the chat says how
 *  it ended. Nothing else can be hidden, and a card nobody hid shows its own outcome and adds nothing to the chat. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import * as client from "../api/client";
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
const enroll = (id: string) => ({ type: "propose_enroll_node", call_id: id, name: `mini-${id}`, host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] });

/** an enrolment that never answers until the test says so */
function hungEnroll() {
  let release: () => void = () => {};
  let fail: (e: unknown) => void = () => {};
  const call = vi.spyOn(client.api, "enrollSshNode").mockImplementation(() => new Promise((ok, no) => { release = ok as never; fail = no; }) as never);
  return { call, release: () => release(), fail: (e: unknown) => fail(e) };
}

describe("Hide is the way out of a card whose apply is in flight", () => {
  it("is offered only once the apply is in flight, and goes when it has ended", async () => {
    const hung = hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    expect(screen.queryByTestId("enroll-hide")).toBeNull();
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    expect(screen.getByTestId("enroll-hide")).toHaveTextContent("kit.hide");
    expect(screen.getByTestId("enroll-node-card")).toHaveTextContent("kit.hideHint");
    hung.fail(new Error("host key mismatch"));                        // it ended and the card stays (it shows why)
    await flush();
    expect(screen.getByTestId("enroll-node-card")).toBeInTheDocument();
    expect(screen.queryByTestId("enroll-hide")).toBeNull();
  });

  it("hiding takes the card out of the slot; the apply goes on, once", async () => {
    const hung = hungEnroll();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    fireEvent.click(screen.getByTestId("enroll-hide"));
    expect(screen.queryByTestId("enroll-node-card")).toBeNull();
    expect(state().pendingEnrollNodes).toEqual([]);
    expect(state().cardApply.n1).toEqual({ busy: true, hidden: true });
    expect(hung.call).toHaveBeenCalledTimes(1);
    await flush();
    expect(send).not.toHaveBeenCalled();                              // nothing was answered by hiding
  });

  it("the card behind it moves up", () => {
    hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1")); frame(cmd("c1"));
    advance(ANSWER_GUARD_MS);
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    fireEvent.click(screen.getByTestId("enroll-hide"));
    expect(screen.queryByTestId("enroll-node-card")).toBeNull();
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("echo c1");
    expect(screen.queryByTestId("ask-queue")).toBeNull();
  });

  it("a card that is not busy cannot be hidden, and neither can one that is not there", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1")); frame(cmd("c1"));
    act(() => { state().hideCard("n1"); state().hideCard("c1"); state().hideCard("nope"); });
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

describe("a proposal that is delivered again while its apply is hidden does not bring the card back", () => {
  // A proposal is journaled and replayed to a socket that re-attaches (ws/arslan.py): a reconnect during a hung hidden apply delivers it again.
  it("an enrolment: the card stays gone, and the apply is not started twice", async () => {
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
    hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    frame(enroll("n1"));
    expect(screen.getByTestId("enroll-node-card")).toBeInTheDocument();
    expect(screen.getByTestId("enroll-confirm")).toBeDisabled();
  });

  it("a proposal with another id is a new card, hidden apply or not", () => {
    hungEnroll();
    render(<AskSlot send={vi.fn()} />);
    frame(enroll("n1"));
    advance(ANSWER_GUARD_MS);                                         // a card that comes up where none was answers 500 ms later
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    fireEvent.click(screen.getByTestId("enroll-hide"));
    frame(enroll("n2"));
    expect(state().pendingEnrollNodes.map((c) => c.callId)).toEqual(["n2"]);
  });
});

describe("an apply that settles in another conversation tells nobody there", () => {
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
  it("every language has Hide, its hint and the two ways a hidden apply ends, each naming the thing", async () => {
    const files = await Promise.all(["en", "zh", "ja", "es", "de", "fr"].map(async (l) => [l, (await import(`../locales/${l}.json`)).default.kit] as const));
    for (const [lang, kit] of files) {
      for (const key of ["hide", "hideHint", "hiddenEnrolled", "hiddenEnrollFailed"]) {
        expect(kit[key], `${lang} kit.${key}`).toBeTypeOf("string");
        expect(kit[key].trim().length, `${lang} kit.${key}`).toBeGreaterThan(0);
      }
      for (const key of ["hiddenEnrolled", "hiddenEnrollFailed"]) expect(kit[key], `${lang} kit.${key}`).toContain("{{name}}");
      for (const key of ["hiddenEnrollFailed"]) expect(kit[key], `${lang} kit.${key}`).toContain("{{why}}");
    }
  });
});

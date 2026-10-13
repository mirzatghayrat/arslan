/** 0.1.61 §A4 (PR 2b Task 3, re-review 2): one gesture answers one card in the Inbox too. The Inbox's list is empty for a moment after
 *  its last card is answered (the component draws nothing), and the next command of the turn can be waiting already when the list is
 *  fetched again: it comes up under the pointer of a double-click. The guard is kept above the queue, as the chat's slot does. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import InboxApprovals from "../components/proactive/InboxApprovals";

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

const ask = (id: string, pretty: string) => ({ call_id: id, conversation_id: "conv-1", opened_at: 1000, expires_at: Date.now() / 1000 + 1700,
  frame: { type: "propose_run_command", call_id: id, pretty, reason: "" } });
const settle = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

function server(afterFirst: ReturnType<typeof ask>[]) {
  let pending = [ask("a", "echo harmless")];
  const answered: string[] = [];
  vi.spyOn(client, "request").mockImplementation(async (path: string) => {
    const m = /^\/approvals\/(\w+)\/answer$/.exec(path);
    if (m) { answered.push(m[1]); pending = m[1] === "a" ? afterFirst : []; return { ok: true } as never; }    // the turn goes on: its next command is proposed at once
    return pending as never;
  });
  return answered;
}

describe("the Inbox: one gesture answers one card", () => {
  it("the next command of the turn, waiting when the list is fetched again, is not answered by the second click of a double-click", async () => {
    const answered = server([ask("b", "rm -rf ~/Documents")]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await settle();
    fireEvent.click(screen.getByTestId("runcmd-run"));                    // click 1: answers a
    await settle(50);                                                       // the list is fetched again: b is up
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("rm -rf ~/Documents");
    fireEvent.click(screen.getByTestId("runcmd-run"));                    // click 2 of the double-click
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    await settle();
    expect(answered).toEqual(["a"]);
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("rm -rf ~/Documents");
  });

  it("500 ms after a left, b answers normally", async () => {
    const answered = server([ask("b", "rm -rf ~/Documents")]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await settle();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await settle(500);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await settle();
    expect(answered).toEqual(["a", "b"]);
  });

  it("a card that comes up in an Inbox that has been empty for a while answers at once", async () => {
    const answered = server([]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await settle();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await settle(600);                                                      // empty for a good while
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
    expect(answered).toEqual(["a"]);
  });
});

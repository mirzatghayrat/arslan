/** 0.1.61 §A4 (PR 2b Task 3, fix round 1, R4): every pending card stays answerable. The store keeps each kind's cards as a
 *  list keyed by call_id and the slot pages through all of them: a second card of a kind (a window's own run-command card and
 *  a job's, say) waits behind the first and never replaces it; an answer, card_resolved and expiry remove a card by its id
 *  only; each card runs out on its own clock. Enroll-node cards are cards of the same slot (R5). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { ANSWER_GUARD_MS } from "../components/kit";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); clock(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const clock = () => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-13T10:00:00Z")); };
/** the card on top changed — one left, or one came up where none was (final review, I3): it answers once the answer guard has run out */
const settle = () => advance(ANSWER_GUARD_MS);
const state = () => useArslanStore.getState();

const CAPABILITY = { type: "propose_capability", kind: "mcp", name: "excel-mcp-server", summary: "Reads .xlsx",
  source_url: "https://github.com/a/b", repo: "a/b", version: "1.1.2", license: { spdx: "MIT", read_from: "github:LICENSE" }, stars: 1,
  pushed_days: 10, runtime: "uv", runtime_download: null, remote_host: null, network: false, folders: [], keys: [], why: "w", retry: "r" };

type Make = (id: string, extra?: Record<string, unknown>) => Record<string, unknown>;
interface Kind {
  name: string;
  /** the store's list for this kind, the card's test id, the frame for a card with this call id */
  list: "pendingCommands" | "pendingWorkspaceWrites" | "pendingSchedules" | "pendingActions" | "pendingCapabilities" | "pendingEnrollNodes";
  card: string;
  make: Make;
  /** answers the card shown (a yes, or the one No that needs no server), and the frame that goes out for it (none: nothing is sent) */
  answer: () => void;
  sent: ((id: string) => unknown) | null;
}
const click = (id: string) => () => { fireEvent.click(screen.getByTestId(id)); };

const KINDS: Kind[] = [
  { name: "a command card", list: "pendingCommands", card: "runcmd-card",
    make: (id, x) => ({ type: "propose_run_command", call_id: id, pretty: `ls ${id}`, reason: "", options: ["once", "conversation"], ...x }),
    answer: click("runcmd-run"), sent: (id) => ({ type: "confirm_run_command", call_id: id, scope: "once" }) },
  { name: "a write card", list: "pendingWorkspaceWrites", card: "wswrite-card",
    make: (id, x) => ({ type: "propose_workspace_write", call_id: id, workspace: "/w", action: "write_file", path: `${id}.md`, options: ["once", "conversation"], ...x }),
    answer: click("wswrite-allow"), sent: (id) => ({ type: "confirm_workspace_write", call_id: id, scope: "once" }) },
  { name: "a schedule card", list: "pendingSchedules", card: "schedule-card",
    make: (id, x) => ({ type: "propose_schedule", call_id: id, name: `n-${id}`, when: "every: 60", options: ["once", "conversation"], ...x }),
    answer: click("schedule-allow"), sent: (id) => ({ type: "confirm_schedule", call_id: id, scope: "once" }) },
  { name: "an action card", list: "pendingActions", card: "action-card",
    make: (id, x) => ({ type: "propose_action", call_id: id, kind: "app", target: `x-${id}`, detail: "", title: `Use ${id}?`, options: ["task", "conversation"], ...x }),
    answer: click("action-allow"), sent: (id) => ({ type: "confirm_action", call_id: id, scope: "task" }) },
  { name: "a capability card", list: "pendingCapabilities", card: "capability-card",
    make: (id, x) => ({ ...CAPABILITY, call_id: id, ...x }),
    answer: click("capability-card-allow"), sent: (id) => ({ type: "confirm_capability", call_id: id, keys: {}, folders: [] }) },
  { name: "an enroll-node card", list: "pendingEnrollNodes", card: "enroll-node-card",
    make: (id, x) => ({ type: "propose_enroll_node", call_id: id, name: `mini-${id}`, host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"], ...x }),
    answer: click("enroll-cancel"), sent: null },
];
const ids = (k: Kind) => (state()[k.list] as { callId: string }[]).map((c) => c.callId);

describe.each(KINDS)("two $name cards", (k) => {
  it("wait together: the second never replaces the first, and the slot pages through both", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(k.make("a"));
    frame(k.make("b"));
    expect(ids(k)).toEqual(["a", "b"]);
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('"index":1,"total":2');
    expect(screen.getAllByTestId(k.card)).toHaveLength(1);                         // one card at a time, "‹ 1 / 2 ›"
  });

  it("are answered in turn, oldest first: the second moves up when the first is answered", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(k.make("a"));
    frame(k.make("b"));
    settle();                                                                      // a came up where none was
    k.answer();
    expect(ids(k)).toEqual(["b"]);
    expect(screen.getByTestId(k.card)).toBeInTheDocument();
    expect(screen.queryByTestId("ask-queue")).toBeNull();                          // one left: no pager
    settle();
    k.answer();
    expect(ids(k)).toEqual([]);
    expect(screen.queryByTestId("ask-slot")).toBeNull();
    if (k.sent) expect(send.mock.calls).toEqual([[k.sent("a")], [k.sent("b")]]);   // each answer carries its own call id
    else expect(send).not.toHaveBeenCalled();
  });

  it("when the server resolves one, the other stays and is shown", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(k.make("a"));
    frame(k.make("b"));
    frame({ type: "card_resolved", call_id: "a", outcome: "approved", by: "phone" });
    expect(ids(k)).toEqual(["b"]);
    expect(screen.getByTestId(k.card)).toBeInTheDocument();
    frame({ type: "card_resolved", call_id: "zzz", outcome: "approved", by: "phone" });
    expect(ids(k)).toEqual(["b"]);                                                  // an id that is not pending resolves nothing
  });

  it("each runs out on its own clock: the first leaves at its 30 minutes, the second at its own", () => {
    clock();
    render(<AskSlot send={vi.fn()} />);
    frame(k.make("a"));
    advance(600_000);                                                               // ten minutes later
    frame(k.make("b"));
    advance(1_202_000);                                                             // 30 minutes and 2 s after "a" arrived
    expect(ids(k)).toEqual(["b"]);
    expect(screen.getByTestId(k.card)).toBeInTheDocument();
    expect(screen.queryByTestId("ask-expired")).toBeNull();                         // a card is still waiting
    advance(598_000);                                                               // "b"'s own 30 minutes are up: the server closes it first
    expect(ids(k)).toEqual(["b"]);
    advance(2_000);                                                                 // and 2 s later the slot does
    expect(ids(k)).toEqual([]);
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it("sent again with the same call id it is one card, not two", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(k.make("a"));
    frame(k.make("a"));
    expect(ids(k)).toEqual(["a"]);
    expect(screen.queryByTestId("ask-queue")).toBeNull();
  });

  it("expireCard closes the one named and leaves the other", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(k.make("a"));
    frame(k.make("b"));
    act(() => { state().expireCard("a"); });
    expect(ids(k)).toEqual(["b"]);
    expect(state().cardExpired).toBe(true);
  });
});

describe("a window's card and a job's card of the same kind", () => {
  const RULE = (id: string, extra: Record<string, unknown> = {}) => ({ type: "propose_run_command", call_id: id, command: "rm", argv: ["-rf", "build"],
    pretty: "rm -rf build", reason: "deletes files", options: ["once", "conversation", "always"], always_label: "deletes files",
    perm_kind: "command", ...extra });

  it("are both answerable in turn, each with its own scope, and what was ticked on the first never reaches the second", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(RULE("w1"));
    frame(RULE("j1", { background: true }));
    settle();                                                                                // w1 came up where none was
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('"index":1,"total":2');
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");           // the window's, which came first
    fireEvent.click(screen.getByTestId("runcmd-scope-always"));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenLastCalledWith({ type: "confirm_run_command", call_id: "w1", scope: "always" });
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");        // the job's moves up
    expect((screen.getByTestId("runcmd-scope-once") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("runcmd-scope-always") as HTMLInputElement).checked).toBe(false);
    settle();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenLastCalledWith({ type: "confirm_run_command", call_id: "j1", scope: "once" });
    expect(send).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });

  it("the second can be answered first by paging to it; the first stays and is answerable after", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(RULE("w1"));
    frame(RULE("j1", { background: true }));
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
    settle();                                                                                // the card paged to answers after the guard
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).toHaveBeenLastCalledWith({ type: "cancel_run_command", call_id: "j1" });
    expect(state().pendingCommands.map((c) => c.callId)).toEqual(["w1"]);
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");
    settle();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenLastCalledWith({ type: "confirm_run_command", call_id: "w1", scope: "once" });
  });

  it("a note typed on one is sent for that one, and the other starts with no note", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(RULE("w1"));
    frame(RULE("j1", { background: true }));
    settle();
    fireEvent.click(screen.getByTestId("runcmd-note-open"));
    fireEvent.change(screen.getByTestId("runcmd-note-input"), { target: { value: "not this one" } });
    fireEvent.click(screen.getByTestId("runcmd-note-send"));
    expect(send).toHaveBeenLastCalledWith({ type: "cancel_run_command", call_id: "w1", note: "not this one" });
    expect(screen.queryByTestId("runcmd-note-input")).toBeNull();
    expect(state().pendingCommands.map((c) => c.callId)).toEqual(["j1"]);
  });

  it("the job's card being resolved elsewhere leaves the window's; the window's being resolved leaves the job's", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(RULE("w1"));
    frame(RULE("j1", { background: true }));
    frame({ type: "card_resolved", call_id: "j1", outcome: "approved", by: "phone" });
    expect(state().pendingCommands.map((c) => c.callId)).toEqual(["w1"]);
    frame(RULE("j2", { background: true }));
    frame({ type: "card_resolved", call_id: "w1", outcome: "declined", by: "mac" });
    expect(state().pendingCommands.map((c) => c.callId)).toEqual(["j2"]);
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
  });

  it("the order is the order they arrived in, whatever their kind", () => {
    clock();
    frame(RULE("w1"));
    advance(1_000);
    frame({ type: "propose_action", call_id: "a1", kind: "app", target: "x", detail: "", title: "Use x?", options: ["task", "conversation"] });
    advance(1_000);
    frame(RULE("j1", { background: true }));
    render(<AskSlot send={vi.fn()} />);
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('"index":1,"total":3');
    expect(screen.getByTestId("runcmd-card")).toBeInTheDocument();                           // w1 first
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect(screen.getByTestId("action-card")).toBeInTheDocument();                           // then a1
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");        // then j1
  });
});

describe("the cards of every kind, together", () => {
  it("cards that arrive in the same millisecond keep the order they arrived in, whatever their kind", () => {
    clock();                                                                          // the clock stands still: all four arrive at one instant
    frame(KINDS[2].make("s1"));                                                       // a schedule, then an action, then a command, then a write
    frame(KINDS[3].make("a1"));
    frame(KINDS[0].make("c1"));
    frame(KINDS[1].make("w1"));
    render(<AskSlot send={vi.fn()} />);
    const cards = ["schedule-card", "action-card", "runcmd-card", "wswrite-card"];
    const shown = () => cards.find((id) => screen.queryByTestId(id));
    const order: (string | undefined)[] = [];
    for (let i = 0; i < 4; i++) { order.push(shown()); fireEvent.click(screen.getByLabelText("kit.next")); }
    expect(order).toEqual(cards);                                                     // not the order of their kinds
  });

  it("a card sent again goes to the back of the queue, even in the same millisecond", () => {
    clock();
    frame(KINDS[0].make("c1"));
    frame(KINDS[3].make("a1"));
    frame(KINDS[0].make("c1"));                                                       // sent again: now the newest
    render(<AskSlot send={vi.fn()} />);
    expect(screen.getByTestId("action-card")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect(screen.getByTestId("runcmd-card")).toBeInTheDocument();
  });

  it("a new conversation starts with no card of any kind waiting", () => {
    for (const k of KINDS) frame(k.make("a"));
    expect(KINDS.every((k) => ids(k).length === 1)).toBe(true);
    act(() => { state().resetForNewConversation(); });
    for (const k of KINDS) expect(ids(k), k.name).toEqual([]);
  });

  it("an enroll-node card counts down to the 30 minutes it is held for", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(KINDS[5].make("a"));
    expect(screen.getByTestId("ask-countdown")).toHaveAccessibleName(/^(30:00|29:\d\d)$/);
  });
});

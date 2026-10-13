/** 0.1.61 §A4 through the chat's ask slot: a v2 frame's choices and expiry, the frames it answers
 *  with, a card answered by a typed message, and a card that runs out — "waiting for you". */
import { useState } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskForFrame from "../components/AskForFrame";
import AskSlot from "../components/AskSlot";
import RunCommandCard from "../components/RunCommandCard";
import { AskQueue } from "../components/kit";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => { cleanup(); vi.useRealTimers(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const RULE = { type: "propose_run_command", call_id: "c1", command: "rm", argv: ["-rf", "build"], pretty: "rm -rf build",
  reason: "deletes files", options: ["once", "conversation", "always"], always_label: "deletes files",
  title: "Run `rm -rf build`?", perm_kind: "command" };

describe("card v2 in the chat", () => {
  it("a rule card offers its scopes and answers with the one chosen — no 'remember'", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...RULE, expires_at: Date.now() / 1000 + 1800 });
    fireEvent.click(screen.getByLabelText('kit.scope.always:{"label":"deletes files"}'));
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "c1", scope: "always" }]]);
  });

  it("an app card's first choice is For this task, and its title is the frame's", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ type: "propose_action", call_id: "a1", kind: "app", target: "com.tencent.xinWeChat", detail: "", title: "Use WeChat?",
            options: ["task", "conversation", "always"], always_label: "WeChat", perm_kind: "app", expires_at: Date.now() / 1000 + 1800 });
    expect(screen.getByTestId("action-title")).toHaveTextContent("Use WeChat?");
    fireEvent.click(screen.getByTestId("action-allow"));
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_action", call_id: "a1", scope: "task" }]]);
  });

  it("No with a note sends the note; esc sends a plain No", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ type: "propose_schedule", call_id: "s1", name: "digest", when: "every: 86400", options: ["once", "conversation"] });
    fireEvent.click(screen.getByText("kit.noteLink"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "weekly is enough" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", metaKey: true });
    expect(send.mock.calls.at(-1)).toStrictEqual([{ type: "cancel_schedule", call_id: "s1", note: "weekly is enough" }]);
    frame({ type: "propose_schedule", call_id: "s2", name: "x", when: "y", options: ["once", "conversation"] });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send.mock.calls.at(-1)).toStrictEqual([{ type: "cancel_schedule", call_id: "s2" }]);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("a write card's yes is the scope the user picked", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ type: "propose_workspace_write", call_id: "w1", workspace: "/Users/me/Arslan", action: "write_file", path: "a.md",
            options: ["once", "conversation"] });
    fireEvent.click(screen.getByTestId("wswrite-scope-conversation"));
    fireEvent.click(screen.getByTestId("wswrite-allow"));
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_workspace_write", call_id: "w1", scope: "conversation" }]]);
  });

  it("a choice made on one card never carries to the next card of the same kind", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...RULE, call_id: "c1" });
    fireEvent.click(screen.getByTestId("runcmd-scope-always"));
    frame({ ...RULE, call_id: "c2" });                                   // replaces c1 in the one command slot
    expect((screen.getByTestId("runcmd-scope-once") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send.mock.calls.at(-1)).toStrictEqual([{ type: "confirm_run_command", call_id: "c2", scope: "once" }]);
  });

  it("the countdown is the server's thirty minutes, and the time really left after a reload", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a.md",
            options: ["once", "conversation"], expires_at: Date.now() / 1000 + 1790 });
    expect(screen.getByTestId("ask-countdown")).toHaveAccessibleName(/^29:\d\d$/);
    cleanup();
    useArslanStore.setState(initialArslanState(), true);                 // a reload: the card is replayed
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a.md",
            options: ["once", "conversation"], expires_at: Date.now() / 1000 + 600 });
    expect(screen.getByTestId("ask-countdown")).toHaveAccessibleName(/^(10:00|9:\d\d)$/);
  });

  it("a frame without expires_at counts down the thirty minutes the Mac waits, not five", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_run_command", call_id: "o1", command: "mv", argv: ["a", "b"], pretty: "mv a b", reason: "", sandbox: "retry" });
    expect(screen.getByTestId("ask-countdown")).toHaveAccessibleName(/^(30:00|29:\d\d)$/);
  });

  it("a card answered by a message typed meanwhile (card_resolved, declined) leaves and says nothing more", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...RULE, expires_at: Date.now() / 1000 + 1800 });
    frame({ type: "card_resolved", call_id: "c1", outcome: "declined", by: "mac" });
    expect(screen.queryByTestId("ask-slot")).toBeNull();
    expect(send).not.toHaveBeenCalled();
  });

  it("a card that runs out leaves at its expiry and the slot says it is waiting for you, not declined", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-12T10:00:00Z"));
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...RULE, expires_at: Date.now() / 1000 + 1800 });
    act(() => { vi.advanceTimersByTime(1_800_000); });
    expect(screen.getByTestId("runcmd-card")).toBeInTheDocument();       // the server closes it first
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
    expect(screen.getByTestId("ask-expired")).toHaveTextContent("kit.expiredTitle");
    expect(screen.getByTestId("ask-expired")).toHaveTextContent("kit.expiredBody");
    expect(screen.getByTestId("ask-slot").textContent).not.toMatch(/declin/i);
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("ask-expired-close"));
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });

  it("with two cards waiting, the one that runs out first leaves first, and the notice waits until nothing else does", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-12T10:00:00Z"));
    render(<AskSlot send={vi.fn()} />);
    frame({ ...RULE, expires_at: Date.now() / 1000 + 60 });
    frame({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a.md",
            options: ["once", "conversation"], expires_at: Date.now() / 1000 + 1800 });
    act(() => { vi.advanceTimersByTime(62_000); });                       // the command's expiry + the 2 s grace
    expect(useArslanStore.getState().pendingCommand).toBeNull();
    expect(useArslanStore.getState().pendingWorkspaceWrite?.callId).toBe("w1");
    expect(screen.getByTestId("wswrite-card")).toBeInTheDocument();      // the one left to answer
    expect(screen.queryByTestId("ask-expired")).toBeNull();
    act(() => { vi.advanceTimersByTime(1_740_000); });                    // to the write card's own expiry + 2 s
    expect(screen.queryByTestId("wswrite-card")).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it("a job's card the Mac closes as expired says the same; one approved elsewhere says nothing", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...RULE, background: true });
    frame({ type: "card_resolved", call_id: "c1", outcome: "expired" });
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
    act(() => { useArslanStore.getState().addUserMessage("I'm back"); });
    expect(screen.queryByTestId("ask-expired")).toBeNull();               // the user is back
    frame({ ...RULE, call_id: "c3" });
    frame({ type: "card_resolved", call_id: "c3", outcome: "approved", by: "phone" });
    expect(screen.queryByTestId("ask-slot")).toBeNull();
    frame({ type: "card_resolved", call_id: "never-shown", outcome: "expired" });
    expect(screen.queryByTestId("ask-slot")).toBeNull();                  // not a card shown here
  });
});

// ── What a frame's card fields become in the store ──────────────────────────────────────────────────────

describe("a card frame in the store", () => {
  const FIELDS = { options: ["once", "conversation"], always_label: "the folder", title: "Let Arslan write?", perm_kind: "folder",
                   why: "to save your notes", expires_at: 1_900_000_000.25 };
  const WANT = { options: ["once", "conversation"], alwaysLabel: "the folder", title: "Let Arslan write?", permKind: "folder",
                 why: "to save your notes", expiresAt: 1_900_000_000_250 };           // the expiry in ms
  const slots = () => {
    const s = useArslanStore.getState();
    return { command: s.pendingCommand, write: s.pendingWorkspaceWrite, schedule: s.pendingSchedule, action: s.pendingAction };
  };

  it("keeps every v2 field on every kind of card: choices, literal scope, question, kind, the model's why, expiry in ms", () => {
    frame({ type: "propose_run_command", call_id: "c", pretty: "ls", ...FIELDS });
    frame({ type: "propose_workspace_write", call_id: "w", workspace: "/w", action: "write_file", path: "a", ...FIELDS });
    frame({ type: "propose_schedule", call_id: "s", name: "n", when: "every: 60", ...FIELDS });
    frame({ type: "propose_action", call_id: "a", kind: "app", target: "x", detail: "", ...FIELDS });
    for (const [name, card] of Object.entries(slots())) expect(card, name).toMatchObject(WANT);
  });

  it("an old frame leaves them all off: nothing is invented", () => {
    frame({ type: "propose_workspace_write", call_id: "w", workspace: "/w", action: "write_file", path: "a" });
    frame({ type: "propose_action", call_id: "a", kind: "browser_site", target: "x.com", detail: "click" });
    for (const [name, card] of Object.entries(slots()).filter(([, c]) => c)) {
      for (const k of Object.keys(WANT)) expect(card, `${name}.${k}`).not.toHaveProperty(k);
    }
  });

  it("reads a frame defensively: only strings in the choices, only words, only a finite expiry", () => {
    frame({ type: "propose_schedule", call_id: "s", name: "n", when: "w",
            options: ["once", 3, null, "conversation"], always_label: "", title: 7, perm_kind: "", why: "   ", expires_at: "soon" });
    const card = useArslanStore.getState().pendingSchedule!;
    expect(card.options).toEqual(["once", "conversation"]);
    for (const k of ["alwaysLabel", "title", "permKind", "why", "expiresAt"]) expect(card, k).not.toHaveProperty(k);
    for (const odd of [{ options: "once" }, { options: [] }, { options: [4, null] }, { expires_at: Infinity }, { expires_at: NaN }]) {
      frame({ type: "propose_schedule", call_id: "s2", name: "n", when: "w", ...odd });
      const next = useArslanStore.getState().pendingSchedule!;
      expect(next, JSON.stringify(odd)).not.toHaveProperty(Object.keys(odd)[0] === "options" ? "options" : "expiresAt");
    }
  });

  it("keeps a title trimmed, and a title of spaces is no title", () => {
    frame({ type: "propose_action", call_id: "a", kind: "app", target: "x", detail: "", title: "  Use x?  " });
    expect(useArslanStore.getState().pendingAction?.title).toBe("Use x?");
    frame({ type: "propose_action", call_id: "b", kind: "app", target: "x", detail: "", title: "   " });
    expect(useArslanStore.getState().pendingAction).not.toHaveProperty("title");
  });

  it("closes a card the server says is resolved only if it is the one shown, and only that one", () => {
    frame({ ...RULE, call_id: "c1" });
    frame({ ...RULE, call_id: "c2" });                                   // replaces c1 in the one command slot
    frame({ type: "card_resolved", call_id: "c1", outcome: "expired" }); // c1 is not shown here any more
    expect(useArslanStore.getState().pendingCommand?.callId).toBe("c2");
    expect(useArslanStore.getState().cardExpired).toBe(false);
    frame({ type: "card_resolved", call_id: "c2", outcome: "expired" });
    expect(useArslanStore.getState()).toMatchObject({ pendingCommand: null, cardExpired: true });
  });

  it("expireCard closes a card that is shown here and says it ran out; for any other id it does nothing", () => {
    frame({ ...RULE });
    act(() => { useArslanStore.getState().expireCard("not-this-one"); });
    expect(useArslanStore.getState().pendingCommand).not.toBeNull();
    expect(useArslanStore.getState().cardExpired).toBe(false);
    act(() => { useArslanStore.getState().expireCard("c1"); });
    expect(useArslanStore.getState()).toMatchObject({ pendingCommand: null, cardExpired: true });
    act(() => { useArslanStore.getState().dismissCardExpired(); });
    expect(useArslanStore.getState().cardExpired).toBe(false);
  });

  it("a new conversation starts without the 'waiting for you' notice", () => {
    act(() => { useArslanStore.setState({ cardExpired: true }); });
    act(() => { useArslanStore.getState().resetForNewConversation(); });
    expect(useArslanStore.getState().cardExpired).toBe(false);
  });
});

// ── A choice never carries from one ask to another ──────────────────────────────────────────────────────

describe("a choice never carries from one ask to another", () => {
  // [card, its frame, test-id prefix of its choices, the choice picked, the choice a fresh card starts on]
  const REPLACED: [string, (id: string) => Record<string, unknown>, string, string, string][] = [
    ["a write card", (id) => ({ type: "propose_workspace_write", call_id: id, workspace: "/w", action: "write_file", path: "a.md",
      options: ["once", "conversation"] }), "wswrite-scope", "conversation", "once"],
    ["a schedule card", (id) => ({ type: "propose_schedule", call_id: id, name: "n", when: "every: 60",
      options: ["once", "conversation"] }), "schedule-choice", "conversation", "once"],
    ["an action card", (id) => ({ type: "propose_action", call_id: id, kind: "app", target: "x", detail: "", title: "Use x?",
      options: ["task", "conversation", "always"], always_label: "x" }), "action-scope", "always", "task"],
  ];

  it.each(REPLACED)("%s: what was picked on one ask is not picked on the ask that replaces it", (_name, make, prefix, picked, fresh) => {
    render(<AskSlot send={vi.fn()} />);
    frame(make("k1"));
    fireEvent.click(screen.getByTestId(`${prefix}-${picked}`));
    expect((screen.getByTestId(`${prefix}-${picked}`) as HTMLInputElement).checked).toBe(true);
    frame(make("k2"));
    expect((screen.getByTestId(`${prefix}-${fresh}`) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId(`${prefix}-${picked}`) as HTMLInputElement).checked).toBe(false);
  });

  it("an opened note and what was typed in it do not carry either", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...RULE, call_id: "c1" });
    fireEvent.click(screen.getByTestId("runcmd-note-open"));
    fireEvent.change(screen.getByTestId("runcmd-note-input"), { target: { value: "for the first one" } });
    frame({ ...RULE, call_id: "c2" });
    expect(screen.queryByTestId("runcmd-note-input")).toBeNull();
    fireEvent.click(screen.getByTestId("runcmd-note-open"));
    expect(screen.getByTestId("runcmd-note-input")).toHaveValue("");
  });

  /** Two commands of one kind in one queue: answering the first moves the second up into the same place. */
  function Queue() {
    const [ids, setIds] = useState(["c1", "c2"]);
    const leave = (id: string) => setIds((all) => all.filter((x) => x !== id));
    return <AskQueue items={ids.map((id) => ({ key: `cmd:${id}`, render: (queue) => (
      <RunCommandCard callId={id} pretty={`rm ${id}`} options={["once", "conversation", "always"]} alwaysLabel="deletes files"
        queue={queue} onConfirm={() => leave(id)} onCancel={() => leave(id)} />) }))} />;
  }

  it("in a queue, the ask that moves up into an answered ask's place starts fresh: no Always, no note", () => {
    render(<Queue />);
    fireEvent.click(screen.getByTestId("runcmd-scope-always"));
    fireEvent.click(screen.getByTestId("runcmd-note-open"));
    fireEvent.change(screen.getByTestId("runcmd-note-input"), { target: { value: "for c1" } });
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("rm c1");
    fireEvent.click(screen.getByTestId("runcmd-run"));                    // c1 answered; c2 takes its place in the queue
    expect(screen.getByTestId("runcmd-card")).toHaveTextContent("rm c2");
    expect((screen.getByTestId("runcmd-scope-once") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("runcmd-scope-always") as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByTestId("runcmd-note-input")).toBeNull();
  });
});

// ── What each card gets from its frame through the slot ─────────────────────────────────────────────────

describe("each card is given its frame's fields by the slot", () => {
  // [card, a frame with a literal Always, that Always's label, its yes button, the frame a yes answers, its note's test-id prefix, the frame a No answers]
  const CARDS: [string, Record<string, unknown>, string, string, string, string, string][] = [
    ["the command card", { ...RULE, call_id: "k" }, "deletes files", "runcmd-run", "confirm_run_command", "runcmd-note", "cancel_run_command"],
    ["the write card", { type: "propose_workspace_write", call_id: "k", workspace: "/w", action: "write_file", path: "a.md",
      options: ["once", "conversation", "always"], always_label: "this folder" }, "this folder", "wswrite-allow", "confirm_workspace_write", "wswrite-note", "cancel_workspace_write"],
    ["the schedule card", { type: "propose_schedule", call_id: "k", name: "n", when: "every: 60",
      options: ["once", "conversation", "always"], always_label: "this task" }, "this task", "schedule-allow", "confirm_schedule", "schedule-note", "cancel_schedule"],
    ["the action card", { type: "propose_action", call_id: "k", kind: "app", target: "x", detail: "", title: "Use x?",
      options: ["task", "conversation", "always"], always_label: "x app" }, "x app", "action-allow", "confirm_action", "action-note", "cancel_action"],
  ];

  it.each(CARDS)("%s draws the frame's literal Always, and a yes on it says always", (_name, make, label, allow, type) => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(make);
    fireEvent.click(screen.getByLabelText(`kit.scope.always:{"label":"${label}"}`));
    fireEvent.click(screen.getByTestId(allow));
    expect(send.mock.calls).toStrictEqual([[{ type, call_id: "k", scope: "always" }]]);
    expect(screen.queryByTestId("ask-slot")).toBeNull();                      // answered: it leaves
  });

  it.each(CARDS)("%s: No with a note sends the note, esc sends a plain No, and the card leaves each time", (_name, make, _label, _allow, _type, note, cancel) => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(make);
    fireEvent.click(screen.getByTestId(`${note}-open`));
    fireEvent.change(screen.getByTestId(`${note}-input`), { target: { value: "use the other one" } });
    fireEvent.click(screen.getByTestId(`${note}-send`));
    expect(send.mock.calls.at(-1)).toStrictEqual([{ type: cancel, call_id: "k", note: "use the other one" }]);
    expect(screen.queryByTestId("ask-slot")).toBeNull();
    frame({ ...make, call_id: "k2" });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send.mock.calls.at(-1)).toStrictEqual([{ type: cancel, call_id: "k2" }]);
    expect(send).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });

  it.each(CARDS)("%s names the job as the one asking when the frame came from a job, else Arslan", (_name, make) => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...make, background: true });
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
    cleanup();
    useArslanStore.setState(initialArslanState(), true);
    render(<AskSlot send={vi.fn()} />);
    frame(make);
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");
  });
});

// ── The model's own line is the question ────────────────────────────────────────────────────────────────

describe("the model's why is the question (§A4)", () => {
  const ACTION = { type: "propose_action", call_id: "a1", kind: "app", target: "com.tencent.xinWeChat", detail: "", title: "Use WeChat?",
                   options: ["task", "conversation"], perm_kind: "app" };

  it("a card for a kind with no words of its own asks the frame's why, in the person's language, else the server's title", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, why: "把你写的笔记发给小李" });
    expect(screen.getByTestId("action-title")).toHaveTextContent("把你写的笔记发给小李");
    expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");    // the model writes in the person's language
    frame({ ...ACTION, call_id: "a2" });                                       // no why: the server's English title
    expect(screen.getByTestId("action-title")).toHaveTextContent("Use WeChat?");
    expect(screen.getByTestId("action-title")).toHaveAttribute("lang", "en");
  });

  it("a why of nothing but spaces asks the title", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, why: "   " });
    expect(screen.getByTestId("action-title")).toHaveTextContent("Use WeChat?");
  });

  it("a card with words of its own keeps them and shows the frame's why as Arslan says; a blank why shows nothing", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, kind: "desktop_app", target: "Notes", why: "Tidy the notes" });
    expect(screen.getByTestId("action-title")).toHaveTextContent('hands.title.desktop_app:{"target":"Notes"}');
    expect(screen.getByTestId("action-said")).toHaveTextContent("Tidy the notes");
    frame({ ...ACTION, call_id: "a2", kind: "desktop_app", target: "Notes", why: "   " });
    expect(screen.queryByTestId("action-said")).toBeNull();
  });

  it("the model's line never stands alone: the frame's own title is said under it, in the server's words", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ACTION, target: "~/Notes/2025", title: "Delete ~/Notes/2025", why: "Tidy the notes" });
    expect(screen.getByTestId("action-title")).toHaveTextContent("Tidy the notes");
    expect(screen.getByTestId("action-subject")).toHaveTextContent("Delete ~/Notes/2025");
    frame({ ...ACTION, call_id: "a2", target: "~/Notes/2025", title: "Delete ~/Notes/2025" });     // no why: said once, as the heading
    expect(screen.getAllByText("Delete ~/Notes/2025")).toHaveLength(1);
    expect(screen.queryByTestId("action-subject")).toBeNull();
  });
});

// ── The permission kind reaches the command card ────────────────────────────────────────────────────────

describe("a command's permission kind reaches its card", () => {
  it.each([["destructive", true], ["money", true], ["app_risky", true], ["command", false], ["outside", false]])(
    "in the chat, a %s command draws Run red: %s", (perm_kind, red) => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...RULE, perm_kind });
    expect(screen.getByTestId("runcmd-run").className.includes("danger")).toBe(red);
  });

  it.each([["money", true], ["destructive", true], ["app_risky", true], ["app", false]])(
    "in the chat, a %s action draws Allow red: %s", (perm_kind, red) => {
    render(<AskSlot send={vi.fn()} />);
    frame({ type: "propose_action", call_id: "a1", kind: "app", target: "x", detail: "", title: "Do it?", options: ["task", "conversation"], perm_kind });
    expect(screen.getByTestId("action-allow").className.includes("danger")).toBe(red);
  });

  it("in the chat, a money command (once only) offers only its first choice, whatever else the frame lists", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...RULE, perm_kind: "money" });
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_run_command", call_id: "c1", scope: "once" }]]);
  });

  const inbox = (fields: Record<string, unknown>) => ({ call_id: "c1", conversation_id: "conv", opened_at: 1, expires_at: Date.now() / 1000 + 600,
    frame: { type: "propose_run_command", call_id: "c1", pretty: "rm -rf build", reason: "deletes files", ...fields } });

  it.each([["destructive", true], ["money", true], ["app_risky", true], ["command", false], [undefined, false]])(
    "from the Inbox, a %s command draws Run red: %s", (perm_kind, red) => {
    render(<AskForFrame ask={inbox({ perm_kind })} onAnswer={vi.fn()} />);
    expect(screen.getByTestId("runcmd-run").className.includes("danger")).toBe(red);
  });
});

// ── An answer in the chat is never in flight ────────────────────────────────────────────────────────────

describe("an answer given in the chat is never in flight", () => {
  it("every card stays live while its turn waits on it: the answer is a socket write and the card leaves in the same tick", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...RULE });
    frame({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a", options: ["once", "conversation"] });
    frame({ type: "propose_schedule", call_id: "s1", name: "n", when: "every: 60", options: ["once", "conversation"] });
    frame({ type: "propose_action", call_id: "a1", kind: "app", target: "x", detail: "", title: "Use x?", options: ["task", "conversation"] });
    act(() => { useArslanStore.setState({ pending: true, thinking: true, streaming: true, queued: true, activeRunId: 7 }); });
    const cards = [["runcmd-card", "runcmd-run", "runcmd-note"], ["wswrite-card", "wswrite-allow", "wswrite-note"],
                   ["schedule-card", "schedule-allow", "schedule-note"], ["action-card", "action-allow", "action-note"]];
    for (let answered = 0; answered < cards.length; answered++) {
      const [, allow, note] = cards.find(([card]) => screen.queryByTestId(card))!;
      expect(screen.getByTestId(allow)).toBeEnabled();
      fireEvent.click(screen.getByTestId(`${note}-open`));
      expect(screen.getByTestId(`${note}-send`)).toBeEnabled();
      fireEvent.click(screen.getByTestId(allow));
    }
    expect(send).toHaveBeenCalledTimes(4);
    expect(screen.queryByTestId("ask-slot")).toBeNull();
  });
});

// ── After the note answers a card ───────────────────────────────────────────────────────────────────────

describe("after the note answers a card", () => {
  const composers = [["the chat's composer", "chat-message-input"], ["the first-run composer", "landing-message-input"]] as const;
  const answers = [["⏎ in the note", () => fireEvent.keyDown(screen.getByTestId("runcmd-note-input"), { key: "Enter" })],
                   ["the Say no button", () => fireEvent.click(screen.getByTestId("runcmd-note-send"))]] as const;

  describe.each(composers)("with %s", (_what, id) => {
    it.each(answers)("focus is back in it: %s", (_how, answer) => {
      const send = vi.fn();
      render(<><AskSlot send={send} /><input id={id} data-testid="composer" /></>);
      frame({ ...RULE });
      fireEvent.click(screen.getByTestId("runcmd-note-open"));
      screen.getByTestId("runcmd-note-input").focus();
      fireEvent.change(screen.getByTestId("runcmd-note-input"), { target: { value: "use git rm" } });
      answer();
      expect(send.mock.calls).toStrictEqual([[{ type: "cancel_run_command", call_id: "c1", note: "use git rm" }]]);
      expect(screen.queryByTestId("runcmd-card")).toBeNull();
      expect(screen.getByTestId("composer")).toHaveFocus();
    });
  });

  it("a plain No, and a yes, leave the focus where it was", () => {
    render(<><AskSlot send={vi.fn()} /><input id="chat-message-input" data-testid="composer" /><input data-testid="other" /></>);
    frame({ ...RULE });
    screen.getByTestId("other").focus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
    expect(screen.getByTestId("other")).toHaveFocus();
    frame({ ...RULE, call_id: "c2" });
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(screen.getByTestId("other")).toHaveFocus();
  });

  it("with no composer on the page there is nothing to focus, and the answer still goes", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...RULE });
    fireEvent.click(screen.getByTestId("runcmd-note-open"));
    fireEvent.change(screen.getByTestId("runcmd-note-input"), { target: { value: "no" } });
    fireEvent.click(screen.getByTestId("runcmd-note-send"));
    expect(send).toHaveBeenCalledWith({ type: "cancel_run_command", call_id: "c1", note: "no" });
  });
});

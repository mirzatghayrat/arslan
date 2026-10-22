/** 0.1.61 §A4 (PR 2b Task 3 re-review of fix round 1): an answer takes out the card that was answered, by its call id, and sends that
 *  card's own id and scope — also when it is NOT the first card of its list (the person paged to it first). card-lists.test.tsx answers
 *  the first card, then the second, which a slot that takes out "the first of the list" passes; only the command card's Esc was paged. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
/** the card on top changed: it answers once the answer guard (500 ms) has run out */
const settle = () => act(() => { vi.advanceTimersByTime(500); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const state = () => useArslanStore.getState();
const click = (id: string) => () => { fireEvent.click(screen.getByTestId(id)); };
const next = () => { fireEvent.click(screen.getByLabelText("kit.next")); settle(); };

const CAPABILITY = { type: "propose_capability", kind: "mcp", name: "excel-mcp-server", summary: "Reads .xlsx",
  source_url: "https://github.com/a/b", repo: "a/b", version: "1.1.2", license: { spdx: "MIT", read_from: "github:LICENSE" }, stars: 1,
  pushed_days: 10, runtime: "uv", runtime_download: null, remote_host: null, network: false, folders: [], keys: [], why: "w", retry: "r" };

interface Kind {
  name: string;
  list: "pendingCommands" | "pendingWorkspaceWrites" | "pendingSchedules" | "pendingActions" | "pendingCapabilities" | "pendingEnrollNodes";
  make: (id: string, extra?: Record<string, unknown>) => Record<string, unknown>;
  yes: () => void;
  /** the frame the yes sends (none: nothing goes out) and the one a plain No (Esc) sends (none: Esc does not answer it) */
  sentYes: ((id: string) => unknown) | null;
  sentNo: ((id: string) => unknown) | null;
  /** [test-id prefix of its choices, the choice other than the first] for a card that offers choices */
  choices?: [string, string, (id: string) => unknown];
}
const KINDS: Kind[] = [
  { name: "command", list: "pendingCommands", yes: click("runcmd-run"),
    make: (id, x) => ({ type: "propose_run_command", call_id: id, pretty: `ls ${id}`, reason: "", options: ["once", "conversation"], ...x }),
    sentYes: (id) => ({ type: "confirm_run_command", call_id: id, scope: "once" }), sentNo: (id) => ({ type: "cancel_run_command", call_id: id }),
    choices: ["runcmd-scope", "conversation", (id) => ({ type: "confirm_run_command", call_id: id, scope: "conversation" })] },
  { name: "write", list: "pendingWorkspaceWrites", yes: click("wswrite-allow"),
    make: (id, x) => ({ type: "propose_workspace_write", call_id: id, workspace: "/w", action: "write_file", path: `${id}.md`, options: ["once", "conversation"], ...x }),
    sentYes: (id) => ({ type: "confirm_workspace_write", call_id: id, scope: "once" }), sentNo: (id) => ({ type: "cancel_workspace_write", call_id: id }),
    choices: ["wswrite-scope", "conversation", (id) => ({ type: "confirm_workspace_write", call_id: id, scope: "conversation" })] },
  { name: "schedule", list: "pendingSchedules", yes: click("schedule-allow"),
    make: (id, x) => ({ type: "propose_schedule", call_id: id, name: `n-${id}`, when: "every: 60", options: ["once", "conversation"], ...x }),
    sentYes: (id) => ({ type: "confirm_schedule", call_id: id, scope: "once" }), sentNo: (id) => ({ type: "cancel_schedule", call_id: id }),
    choices: ["schedule-choice", "conversation", (id) => ({ type: "confirm_schedule", call_id: id, scope: "conversation" })] },
  { name: "action", list: "pendingActions", yes: click("action-allow"),
    make: (id, x) => ({ type: "propose_action", call_id: id, kind: "app", target: `x-${id}`, detail: "", title: `Use ${id}?`, options: ["task", "conversation"], ...x }),
    sentYes: (id) => ({ type: "confirm_action", call_id: id, scope: "task" }), sentNo: (id) => ({ type: "cancel_action", call_id: id }),
    choices: ["action-scope", "conversation", (id) => ({ type: "confirm_action", call_id: id, scope: "conversation" })] },
  { name: "capability", list: "pendingCapabilities", yes: click("capability-card-allow"),
    make: (id, x) => ({ ...CAPABILITY, call_id: id, ...x }),
    sentYes: (id) => ({ type: "confirm_capability", call_id: id, keys: {}, folders: [] }), sentNo: (id) => ({ type: "cancel_capability", call_id: id }) },
  { name: "enroll-node", list: "pendingEnrollNodes", yes: click("enroll-cancel"),
    make: (id, x) => ({ type: "propose_enroll_node", call_id: id, name: `mini-${id}`, host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"], ...x }),
    sentYes: null, sentNo: null },
];
const ids = (k: Kind) => (state()[k.list] as { callId: string }[]).map((c) => c.callId);

describe.each(KINDS)("two $name cards, the person pages to the second", (k) => {
  it("a yes answers the second: its own id goes out, only it leaves, and the first is still answerable", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(k.make("a")); frame(k.make("b"));
    next();                                                                       // paged to b
    k.yes();
    expect(ids(k)).toEqual(["a"]);
    if (k.sentYes) expect(send.mock.calls).toEqual([[k.sentYes("b")]]);
    else expect(send).not.toHaveBeenCalled();
    settle();                                                                     // a moved up
    k.yes();
    expect(ids(k)).toEqual([]);
    if (k.sentYes) expect(send.mock.calls).toEqual([[k.sentYes("b")], [k.sentYes("a")]]);
  });
});

describe.each(KINDS.filter((k) => k.sentNo))("two $name cards, the person pages to the second and says No", (k) => {
  it("a plain No (Esc) answers the second: its own id goes out, only it leaves", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(k.make("a")); frame(k.make("b"));
    next();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(ids(k)).toEqual(["a"]);
    expect(send.mock.calls).toEqual([[k.sentNo!("b")]]);
  });
});

describe.each(KINDS.filter((k) => k.choices))("two $name cards that offer choices, the person pages to the second", (k) => {
  it("a No with a note answers the second: its own id and the note go out, only it leaves", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(k.make("a")); frame(k.make("b"));
    next();
    const prefix = k.choices![0].replace(/-(scope|choice)$/, "");
    fireEvent.click(screen.getByTestId(`${prefix}-note-open`));
    fireEvent.change(screen.getByTestId(`${prefix}-note-input`), { target: { value: "not this" } });
    fireEvent.click(screen.getByTestId(`${prefix}-note-send`));
    expect(ids(k)).toEqual(["a"]);
    expect(send.mock.calls).toEqual([[{ ...(k.sentNo!("b") as object), note: "not this" }]]);
  });

  it("a yes sends a scope the SECOND card offers, ticked on it, whatever the first card offers", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    // the first card does not offer "conversation" at all; the second does
    frame(k.make("a", { options: k.name === "action" ? ["task"] : ["once"] }));
    frame(k.make("b"));
    next();
    fireEvent.click(screen.getByTestId(`${k.choices![0]}-${k.choices![1]}`));
    k.yes();
    expect(send.mock.calls).toEqual([[k.choices![2]("b")]]);
    expect(ids(k)).toEqual(["a"]);
  });
});

/** 0.1.61 §A4: each of the four asking cards offers the frame's choices, answers with the one
 *  chosen, takes a note on No, and stays exactly as before for a frame without choices. */
import type { ReactElement } from "react";
import { describe, it, expect, vi, afterEach, type Mock } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import ActionApprovalCard from "../components/ActionApprovalCard";
import RunCommandCard from "../components/RunCommandCard";
import ScheduleGrantCard from "../components/ScheduleGrantCard";
import WorkspaceWriteCard from "../components/WorkspaceWriteCard";
import { ONCE_ONLY_KINDS, RED_KINDS } from "../components/kit/askParts";
import { handsMessages } from "../locales/hands";

afterEach(() => cleanup());

describe("a rule card (run a command)", () => {
  it("offers its scopes instead of the old tick, a job's card too, and answers with the one chosen", () => {
    const onConfirm = vi.fn();
    render(<RunCommandCard callId="c1" pretty="rm -rf build" reason="deletes files" background
      options={["once", "conversation", "always"]} alwaysLabel="deletes files" onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.queryByTestId("runcmd-remember")).toBeNull();
    expect((screen.getByTestId("runcmd-scope-once") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByLabelText('kit.scope.always:{"label":"deletes files"}'));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(onConfirm).toHaveBeenCalledWith("c1", false, "always");
  });

  it("S4a: the card to leave the sandbox says what its \"In this conversation\" lets out, and answers with it", () => {
    const onConfirm = vi.fn();
    render(<RunCommandCard callId="c5" pretty="mv a ~/b" sandbox="retry" permKind="outside"
      options={["once", "conversation"]} onConfirm={onConfirm} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('kit.scope.conversationFor:{"label":"runcmd.sandboxConversation"}'));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(onConfirm).toHaveBeenCalledWith("c5", false, "conversation");
    cleanup();
    // Another kind's card keeps the plain choice: the label is the outside card's own.
    render(<RunCommandCard callId="c6" pretty="ls" permKind="network" options={["once", "conversation"]}
      onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByLabelText("kit.scope.conversation")).toBeInTheDocument();
  });

  it("No with a note sends it; No without one sends none", () => {
    const onCancel = vi.fn();
    render(<RunCommandCard callId="c2" pretty="rm a" options={["once", "conversation"]} onConfirm={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: " not that one " } });
    fireEvent.click(screen.getByText("kit.noteSend"));
    expect(onCancel).toHaveBeenLastCalledWith("c2", "not that one");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });   // still open: same card
    fireEvent.click(screen.getByText("kit.noteSend"));
    expect(onCancel.mock.calls.at(-1)).toStrictEqual(["c2"]);              // an empty note is a plain No
    fireEvent.click(screen.getByTestId("runcmd-cancel"));
    expect(onCancel.mock.calls.at(-1)).toStrictEqual(["c2"]);                     // the plain No button
  });

  it("an old frame (no options) keeps the tick, answers (callId, remember) and has no note", () => {
    const onConfirm = vi.fn();
    render(<RunCommandCard callId="c3" pretty="git status" onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByText("kit.noteLink")).toBeNull();
    fireEvent.click(screen.getByTestId("runcmd-remember"));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(onConfirm).toHaveBeenCalledWith("c3", true);
  });

  it("in the Inbox an old frame's tick is not offered: the server never keeps it there", () => {
    const onConfirm = vi.fn();
    render(<RunCommandCard callId="c4" pretty="mv a b" sandbox="retry" noRemember onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.queryByTestId("runcmd-remember")).toBeNull();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(onConfirm).toHaveBeenCalledWith("c4", false);
  });
});

describe("the write and schedule cards", () => {
  it("a write card offers Once / In this conversation and answers the scope", () => {
    const onConfirm = vi.fn();
    render(<WorkspaceWriteCard callId="w1" workspace="/Users/me/Arslan" action="write_file" path="a.md"
      options={["once", "conversation"]} onConfirm={onConfirm} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByTestId("wswrite-scope-conversation"));
    fireEvent.click(screen.getByTestId("wswrite-allow"));
    expect(onConfirm).toHaveBeenCalledWith("w1", "conversation");
  });

  it("a schedule card says what an unattended run does, not 'for the rest of this session'", () => {
    const onConfirm = vi.fn(), onCancel = vi.fn();
    render(<ScheduleGrantCard callId="s1" name="digest" when="every: 86400" options={["once", "conversation"]}
      onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByTestId("schedule-unattended")).toHaveTextContent("schedgrant.unattended");
    fireEvent.click(screen.getByTestId("schedule-allow"));
    expect(onConfirm).toHaveBeenCalledWith("s1", "once");
    fireEvent.click(screen.getByText("kit.noteLink"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "weekly is enough" } });
    fireEvent.click(screen.getByText("kit.noteSend"));
    expect(onCancel).toHaveBeenCalledWith("s1", "weekly is enough");
  });
});

describe("an action card", () => {
  it("an app card's first choice is For this task, and a kind it has no words for reads the frame's title", () => {
    const onConfirm = vi.fn();
    render(<ActionApprovalCard kind="app" target="com.tencent.xinWeChat" detail="" title="Use WeChat?"
      options={["task", "conversation", "always"]} alwaysLabel="WeChat" onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.getByTestId("action-title")).toHaveTextContent("Use WeChat?");
    expect(screen.queryByText(/hands\.scope\./)).toBeNull();
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");   // the window asks, not a job
    fireEvent.click(screen.getByTestId("action-allow"));
    expect(onConfirm).toHaveBeenCalledWith("task");
  });

  it("a known kind keeps its own words; money draws Allow red", () => {
    render(<ActionApprovalCard kind="desktop_app" target="Shop" detail="Buy" title="Pay $3?" permKind="money"
      options={["once"]} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("action-title")).toHaveTextContent('hands.title.desktop_app:{"target":"Shop"}');
    expect(screen.queryByRole("radiogroup")).toBeNull();                     // one choice: nothing to pick
    expect(screen.getByText("hands.scope.desktop_app")).toBeInTheDocument();  // no choice says how long: the kind's own whole line stays
    expect(screen.getByTestId("action-allow").className).toContain("danger");
  });

});

// ── What the brief's tests leave open, checked on all four cards ────────────────────────────────────────

type Spy = Mock<(...args: unknown[]) => void>;
interface Mount { options?: string[]; alwaysLabel?: string; busy?: boolean; onConfirm: Spy; onCancel: Spy }
interface Row {
  name: string;
  mount: (p: Mount) => ReactElement;
  /** test-id prefixes: the choices, the note line; and the card's own Allow and No buttons */
  choices: string; note: string; allow: string; deny: string;
  /** the arguments a yes carries for a scope, and a No for a note (none typed = a plain No) */
  yesArgs: (scope: string) => unknown[];
  noArgs: (note?: string) => unknown[];
  /** the arguments of a yes on a card with no choices: what an old card has always sent. Only the command card still
   *  takes an old frame; the write, schedule and action cards always come with options (C2c: permissions.decide). */
  oldYesArgs?: unknown[];
}

const CARDS: Row[] = [
  { name: "run a command", choices: "runcmd-scope", note: "runcmd-note", allow: "runcmd-run", deny: "runcmd-cancel",
    mount: (p) => <RunCommandCard callId="r1" pretty="rm a" {...p} />,
    yesArgs: (scope) => ["r1", false, scope], noArgs: (note) => (note ? ["r1", note] : ["r1"]), oldYesArgs: ["r1", false] },
  { name: "write", choices: "wswrite-scope", note: "wswrite-note", allow: "wswrite-allow", deny: "wswrite-deny",
    mount: (p) => <WorkspaceWriteCard callId="w1" workspace="/w" action="write_file" path="a.md" {...p} />,
    yesArgs: (scope) => ["w1", scope], noArgs: (note) => (note ? ["w1", note] : ["w1"]) },
  { name: "schedule", choices: "schedule-choice", note: "schedule-note", allow: "schedule-allow", deny: "schedule-deny",
    mount: (p) => <ScheduleGrantCard callId="s1" name="digest" when="every: 86400" {...p} />,
    yesArgs: (scope) => ["s1", scope], noArgs: (note) => (note ? ["s1", note] : ["s1"]) },
  { name: "action", choices: "action-scope", note: "action-note", allow: "action-allow", deny: "action-deny",
    mount: (p) => <ActionApprovalCard kind="app" target="com.example.App" detail="" title="Use App?" {...p} />,
    yesArgs: (scope) => [scope], noArgs: (note) => (note ? [note] : []) },
];

const spies = () => ({ onConfirm: vi.fn<(...args: unknown[]) => void>(), onCancel: vi.fn<(...args: unknown[]) => void>() });

describe.each(CARDS)("the $name card", (row) => {
  it("never starts on Always, even when the frame lists it first; Always is sent only when picked", () => {
    const { onConfirm, onCancel } = spies();
    render(row.mount({ options: ["always", "once", "conversation"], alwaysLabel: "that kind", onConfirm, onCancel }));
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios.map((r) => [r.value, r.checked])).toEqual([["always", false], ["once", true], ["conversation", false]]);
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("once"));
    fireEvent.click(screen.getByTestId(`${row.choices}-always`));
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("always"));
  });

  it("a pick the frame still shows is kept; one it no longer shows is never sent (Always loses its literal scope)", () => {
    const { onConfirm, onCancel } = spies();
    const mount = (label: string) => row.mount({ options: ["once", "conversation", "always"], alwaysLabel: label, onConfirm, onCancel });
    const { rerender } = render(mount("that kind"));
    fireEvent.click(screen.getByTestId(`${row.choices}-always`));
    expect((screen.getByTestId(`${row.choices}-always`) as HTMLInputElement).checked).toBe(true);
    rerender(mount("another kind"));                                            // still shown, under another label: kept
    expect((screen.getByTestId(`${row.choices}-always`) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("always"));
    rerender(mount(""));                                                        // no literal scope: Always is gone
    expect(screen.queryByTestId(`${row.choices}-always`)).toBeNull();
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("once"));      // the card's first, never the stale pick
  });

  it("draws Always only with its literal scope: without one the person cannot be led into it", () => {
    const { onConfirm, onCancel } = spies();
    render(row.mount({ options: ["always", "once", "conversation"], alwaysLabel: "  ", onConfirm, onCancel }));
    expect((screen.getAllByRole("radio") as HTMLInputElement[]).map((r) => r.value)).toEqual(["once", "conversation"]);
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("once"));
  });

  it("with one choice draws no picker and sends that choice", () => {
    const { onConfirm, onCancel } = spies();
    render(row.mount({ options: ["once"], onConfirm, onCancel }));
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getByTestId(row.allow)).toBeEnabled();
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("once"));
  });

  it.each([
    ["only ids the card does not know", ["forever"], undefined],
    ["an Always without its literal scope", ["always"], ""],
    ["a mix of both", ["always", "forever"], "   "],
  ])("when the frame shows nothing sendable (%s), Allow is disabled, by button and by ⌘⏎; No still answers", (_why, options, alwaysLabel) => {
    const { onConfirm, onCancel } = spies();
    render(row.mount({ options, alwaysLabel, onConfirm, onCancel }));
    expect(screen.getByTestId(row.allow)).toBeDisabled();
    fireEvent.click(screen.getByTestId(row.allow));
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(onConfirm).not.toHaveBeenCalled();                                    // never a yes with no scope at all
    fireEvent.click(screen.getByTestId(row.deny));
    expect(onCancel.mock.calls.at(-1)).toStrictEqual(row.noArgs());
  });

  it("a lone Always is drawn but never sent unasked: Allow waits until the person picks it", () => {
    const { onConfirm, onCancel } = spies();
    render(row.mount({ options: ["always"], alwaysLabel: "that kind", onConfirm, onCancel }));
    expect((screen.getAllByRole("radio") as HTMLInputElement[]).map((r) => [r.value, r.checked])).toEqual([["always", false]]);
    expect(screen.getByTestId(row.allow)).toBeDisabled();
    fireEvent.click(screen.getByTestId(`${row.choices}-always`));
    expect(screen.getByTestId(row.allow)).toBeEnabled();
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("always"));
  });

  it("No takes the note typed, trimmed; an empty note is a plain No", () => {
    const { onConfirm, onCancel } = spies();
    render(row.mount({ options: ["once", "conversation"], onConfirm, onCancel }));
    fireEvent.click(screen.getByTestId(`${row.note}-open`));
    const box = screen.getByTestId(`${row.note}-input`);
    fireEvent.change(box, { target: { value: "  not that one " } });
    fireEvent.click(screen.getByTestId(`${row.note}-send`));
    expect(onCancel.mock.calls.at(-1)).toStrictEqual(row.noArgs("not that one"));
    fireEvent.change(box, { target: { value: "   " } });
    fireEvent.click(screen.getByTestId(`${row.note}-send`));
    expect(onCancel.mock.calls.at(-1)).toStrictEqual(row.noArgs());
    fireEvent.click(screen.getByTestId(row.deny));
    expect(onCancel.mock.calls.at(-1)).toStrictEqual(row.noArgs());
    expect(onCancel).toHaveBeenCalledTimes(3);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  if (row.oldYesArgs) {
    const oldYesArgs = row.oldYesArgs;
    it.each([["no options", undefined], ["an empty options list", [] as string[]]])(
      "a card with %s offers neither a choice nor a note: a No there would lose the note", (_what, options) => {
      const { onConfirm, onCancel } = spies();
      render(row.mount({ options, onConfirm, onCancel }));
      expect(screen.queryByRole("radiogroup")).toBeNull();
      expect(screen.queryByTestId(`${row.note}-open`)).toBeNull();
      expect(screen.queryByText("kit.noteLink")).toBeNull();
      fireEvent.click(screen.getByTestId(row.allow));
      expect(onConfirm.mock.calls.at(-1)).toStrictEqual(oldYesArgs);            // answered exactly as an old card is
    });
  }

  it("a busy card is inert: its note sends nothing, by key, by button or by submit; the text waits for it", () => {
    const { onConfirm, onCancel } = spies();
    const busy = (b: boolean) => row.mount({ options: ["once", "conversation"], busy: b, onConfirm, onCancel });
    const { rerender } = render(busy(true));
    fireEvent.click(screen.getByTestId(`${row.note}-open`));
    const box = screen.getByTestId(`${row.note}-input`);
    fireEvent.change(box, { target: { value: "wait" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.keyDown(box, { key: "Enter", metaKey: true });
    fireEvent.click(screen.getByTestId(`${row.note}-send`));
    fireEvent.submit(screen.getByTestId(row.note));
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByTestId(`${row.note}-send`)).toBeDisabled();
    expect(screen.getByTestId(row.allow)).toBeDisabled();                     // the card's own buttons too
    expect(screen.getByTestId(row.deny)).toBeDisabled();
    rerender(busy(false));
    expect(screen.getByTestId(`${row.note}-send`)).toBeEnabled();
    fireEvent.keyDown(screen.getByTestId(`${row.note}-input`), { key: "Enter" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCancel.mock.calls[0]).toStrictEqual(row.noArgs("wait"));
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

// ── The permission kind: red Allow, and the once-only kinds ─────────────────────────────────────────────

/** The two cards that carry the frame's permission kind: a command's and an action's. */
const KINDED = [
  { name: "run a command", choices: "runcmd-scope", allow: "runcmd-run",
    mount: (permKind: string | undefined, m: Mount) => <RunCommandCard callId="r1" pretty="rm a" permKind={permKind} {...m} />,
    yesArgs: (scope: string) => ["r1", false, scope] },
  { name: "action", choices: "action-scope", allow: "action-allow",
    mount: (permKind: string | undefined, m: Mount) => (
      <ActionApprovalCard kind="app" target="com.example.App" detail="" title="Use App?" permKind={permKind} {...m} />),
    yesArgs: (scope: string) => [scope] },
];

describe("the kit's one definition of the permission kinds a card treats specially", () => {
  it("red is exactly money, app_risky and destructive; once-only is exactly the server's eight", () => {
    // tests/server/test_card_kinds.py reads these two lists out of kit/askParts.tsx
    expect([...RED_KINDS].sort()).toEqual(["app_risky", "destructive", "money"]);
    expect([...ONCE_ONLY_KINDS].sort()).toEqual(
      ["app_risky", "capability", "money", "opaque", "other_agent", "remote", "system", "takeover"]);
  });
});

describe.each(KINDED)("the $name card and its permission kind", (row) => {
  const mount = (permKind: string | undefined, options?: string[], alwaysLabel?: string) => {
    const { onConfirm, onCancel } = spies();
    render(row.mount(permKind, { options, alwaysLabel, onConfirm, onCancel }));
    return onConfirm;
  };

  it.each(["money", "app_risky", "destructive"])("a %s step draws Allow red", (permKind) => {
    mount(permKind, ["once", "conversation"]);
    expect(screen.getByTestId(row.allow).className).toContain("danger");
  });

  it.each(["command", "send", "outside", "app", "folder", ""])("a step of kind %j does not", (permKind) => {
    mount(permKind, ["once", "conversation"]);
    expect(screen.getByTestId(row.allow).className).not.toContain("danger");
  });

  it("a card with no permission kind is not red either", () => {
    mount(undefined, ["once", "conversation"]);
    expect(screen.getByTestId(row.allow).className).not.toContain("danger");
  });

  it.each(["money", "app_risky", "capability", "other_agent", "system", "opaque", "remote", "takeover"])(
    "a %s card (once only) shows and sends only the frame's first choice, whatever else the frame lists", (permKind) => {
    const onConfirm = mount(permKind, ["once", "conversation", "always"], "that kind");
    expect(screen.queryAllByRole("radio")).toHaveLength(0);                      // one choice: nothing to pick
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("once"));
  });

  it("the first choice is the frame's first, not a fixed word", () => {
    const onConfirm = mount("money", ["task", "once"]);
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("task"));
  });

  it("a pick made while the kind was not once-only is never sent once it is: the send re-checks what the card shows", () => {
    const { onConfirm, onCancel } = spies();
    const asKind = (permKind: string) => row.mount(permKind, { options: ["once", "conversation"], onConfirm, onCancel });
    const { rerender } = render(asKind("app"));
    fireEvent.click(screen.getByTestId(`${row.choices}-conversation`));
    rerender(asKind("money"));
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("once"));
  });

  it("a once-only card whose first choice it cannot show has nothing sendable: Allow stays disabled, whatever else is listed", () => {
    const { onConfirm, onCancel } = spies();
    render(row.mount("money", { options: ["forever", "once"], onConfirm, onCancel }));
    expect(screen.getByTestId(row.allow)).toBeDisabled();
    fireEvent.click(screen.getByTestId(row.allow));
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it.each(["command", "app", "site", "shortcut", "send", undefined])(
    "a card of kind %j keeps every choice the frame lists", (permKind) => {
    const onConfirm = mount(permKind, ["once", "conversation", "always"], "that kind");
    expect((screen.getAllByRole("radio") as HTMLInputElement[]).map((r) => r.value)).toEqual(["once", "conversation", "always"]);
    fireEvent.click(screen.getByTestId(`${row.choices}-conversation`));
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("conversation"));
  });
});

// ── The action card ─────────────────────────────────────────────────────────────────────────────────────

describe("the action card's words, its icon and its red", () => {
  const card = (p: Partial<Parameters<typeof ActionApprovalCard>[0]>) => (
    <ActionApprovalCard kind="desktop_app" target="Notes" detail="click" onConfirm={vi.fn()} onCancel={vi.fn()} {...p} />);

  it("a known kind's whole line yields to a real choice, and stays when there is none to pick", () => {
    const { rerender } = render(card({ options: ["once", "conversation"] }));
    expect(screen.queryByText("hands.scope.desktop_app")).toBeNull();          // two choices say how long themselves
    rerender(card({ options: ["once"] }));
    expect(screen.getByText("hands.scope.desktop_app")).toBeInTheDocument();   // one choice: the kind's own whole line
    rerender(card({}));
    expect(screen.getByText("hands.scope.desktop_app")).toBeInTheDocument();   // an old frame: as before
  });

  it("a kind it has no words for prints no scope line even with one choice (never a raw key)", () => {
    render(card({ kind: "app", title: "Use App?", options: ["once"] }));
    expect(screen.queryByText(/hands\.(scope|grant)\./)).toBeNull();
  });

  it("a hidden option is not a choice: Always without its literal scope leaves one choice, so the whole line stays", () => {
    render(card({ options: ["once", "always"], alwaysLabel: "" }));
    expect(screen.getByText("hands.scope.desktop_app")).toBeInTheDocument();
    expect(screen.queryByText("hands.grant.desktop_app")).toBeNull();
  });

  it("Once + a labelled Always are two choices, so the whole line gives way to what is granted", () => {
    render(card({ options: ["once", "always"], alwaysLabel: "Notes" }));
    expect(screen.queryByText("hands.scope.desktop_app")).toBeNull();
    expect(screen.getByText("hands.grant.desktop_app")).toBeInTheDocument();
  });

  it.each(Object.keys(handsMessages.en.scope))(
    "a %s card with a real choice keeps what is granted and drops only how long", (kind) => {
    const { rerender } = render(card({ kind, options: ["once", "conversation"] }));
    expect(screen.queryByText(`hands.scope.${kind}`)).toBeNull();
    if (kind in handsMessages.en.grant) expect(screen.getByText(`hands.grant.${kind}`)).toBeInTheDocument();
    else expect(screen.queryByText(/hands\.grant\./)).toBeNull();               // a Shortcut's line is only its scope
    rerender(card({ kind, options: ["once"] }));
    expect(screen.getByText(`hands.scope.${kind}`)).toBeInTheDocument();         // no choice: the whole line, as before
    expect(screen.queryByText(/hands\.grant\./)).toBeNull();
  });

  it("four kinds have a grant line (what is granted, apart from for how long), and a Shortcut has none — nor is there a desktop_look card any more", () => {
    expect(Object.keys(handsMessages.en.grant).sort()).toEqual(
      ["browser_site", "desktop_app", "desktop_risky", "mac_script"]);
  });

  it("a kind it has no words for with no title reads its target, never a blank question", () => {
    render(card({ kind: "app", target: "com.example.App", title: "" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("com.example.App");
    cleanup();
    render(card({ kind: "app", target: "com.example.App", title: "Use App?" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("Use App?");
  });

  it("a known kind reads its own words even when the frame brings a title", () => {
    render(card({ title: "Something else entirely?" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent('hands.title.desktop_app:{"target":"Notes"}');
  });

  it("a known kind keeps its own words, with its target, and shows the model's why as 'Arslan says', as the command card does", () => {
    // The kind's own title names what is granted (the website, the app); a model's line must not hide it, and must not be lost.
    render(card({ title: "Something else entirely?", why: "To check the weather" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent('hands.title.desktop_app:{"target":"Notes"}');
    expect(screen.getByTestId("action-title")).not.toHaveTextContent("weather");
    const said = screen.getByTestId("action-said");
    expect(said).toHaveTextContent("kit.arslanSays");
    expect(said).toHaveTextContent("To check the weather");
    expect(said).not.toHaveAttribute("lang");                                           // the model writes in the person's language
  });

  it.each(Object.keys(handsMessages.en.title))("%s: the card's own words are the heading and the model's why is its 'Arslan says' line", (kind) => {
    render(card({ kind, why: "  Tidy the notes  " }));
    expect(screen.getByTestId("action-title")).toHaveTextContent(`hands.title.${kind}`);
    expect(screen.getByTestId("action-said").textContent).toBe("kit.arslanSaysTidy the notes");   // "Arslan says: " + the line, trimmed
  });

  it.each([["spaces", "   "], ["nothing", ""], ["no why at all", undefined]])(
    "a known kind with a why of %s shows no 'Arslan says' line", (_what, why) => {
    render(card({ why }));
    expect(screen.queryByTestId("action-said")).toBeNull();
    expect(screen.queryByText(/kit\.arslanSays/)).toBeNull();
  });

  it("a kind it has no words for puts the why in the heading and not also in an 'Arslan says' line", () => {
    render(card({ kind: "app", title: "Use App?", why: "Tidy the notes" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("Tidy the notes");
    expect(screen.queryByTestId("action-said")).toBeNull();
    expect(screen.getAllByText("Tidy the notes")).toHaveLength(1);
  });

  it("a kind it has no words for asks the model's why when the frame carries one, ahead of the server's title", () => {
    render(card({ kind: "app", title: "Use App?", why: "To send Li the notes you wrote" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("To send Li the notes you wrote");
    expect(screen.getByTestId("action-title")).not.toHaveTextContent("Use App?");
    cleanup();
    render(card({ kind: "app", title: "", target: "com.example.App", why: "To send Li the notes you wrote" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("To send Li the notes you wrote");   // with no title too
  });

  it("the model's line is not the server's English: only the title is tagged lang=en", () => {
    render(card({ kind: "app", title: "Use App?", why: "给小李发笔记" }));
    expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");
    cleanup();
    render(card({ kind: "app", title: "Use App?" }));
    expect(screen.getByTestId("action-title")).toHaveAttribute("lang", "en");
  });

  // A prompt-injected model can word a harmless-sounding why. It may frame the ask; it is never the only description of it.
  describe("what is being approved is said in the server's own words whenever the heading is the model's line", () => {
    const ASK = { kind: "app", target: "~/Notes/2025", title: "Delete ~/Notes/2025", why: "Tidy the notes", detail: "" };

    it("the frame's title sits under a model's line that asks about something else, outside the heading", () => {
      render(card(ASK));
      expect(screen.getByTestId("action-title")).toHaveTextContent("Tidy the notes");
      expect(screen.getByTestId("action-title")).not.toHaveTextContent("Delete ~/Notes/2025");
      expect(screen.getByTestId("action-subject")).toHaveTextContent("Delete ~/Notes/2025");
      expect(screen.getByTestId("action-card")).toHaveTextContent("Delete ~/Notes/2025");
    });

    it("it is the literal title: not translated, not marked as the model's, tagged as the server's English", () => {
      render(card(ASK));
      const subject = screen.getByTestId("action-subject");
      expect(subject.textContent).toBe("Delete ~/Notes/2025");                       // nothing added, nothing looked up
      expect(subject).toHaveAttribute("lang", "en");
      expect(screen.queryByText(/kit\.arslanSays/)).toBeNull();                       // no "Arslan says:" on it
      expect(screen.queryByTestId("action-said")).toBeNull();
      expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");        // the model's own line is not tagged English
    });

    it("it is primary text in the same raised block the command card puts its exact command in: not muted, not small print", () => {
      render(card(ASK));
      const subject = screen.getByTestId("action-subject");
      const classes = subject.className;
      cleanup();
      render(<RunCommandCard callId="r" pretty="rm -rf ~/Notes/2025" onConfirm={vi.fn()} onCancel={vi.fn()} />);
      const block = screen.getByTestId("ask-code").className.split(/\s+/);
      for (const cls of ["rounded-[10px]", "bg-surface-raised", "px-3", "py-2.5"]) {
        expect(block, `the command card's block has ${cls}`).toContain(cls);
        expect(classes.split(/\s+/), `the line under the model's has ${cls}`).toContain(cls);
      }
      expect(classes).toContain("text-foreground");
      expect(classes).not.toContain("text-muted-foreground");
      expect(classes).not.toMatch(/\btext-\[(?:[0-9]|1[0-4])px\]/);                    // not the 14px (or smaller) print it was
      expect(classes).not.toMatch(/\btext-(?:xs|sm)\b/);                                // nor the named small sizes
      expect(classes).not.toMatch(/\bopacity-/);                                        // nor faded
      expect(classes).toContain("font-semibold");
    });

    it("with no title it is the bare target, which is not words and so is not tagged", () => {
      render(card({ ...ASK, title: "" }));
      expect(screen.getByTestId("action-title")).toHaveTextContent("Tidy the notes");
      expect(screen.getByTestId("action-subject").textContent).toBe("~/Notes/2025");
      expect(screen.getByTestId("action-subject")).not.toHaveAttribute("lang");
    });

    it("the frame's own detail stays, under it", () => {
      render(card({ ...ASK, detail: "rm -rf ~/Notes/2025" }));
      const subject = screen.getByTestId("action-subject");
      const detail = screen.getByText("rm -rf ~/Notes/2025");
      expect(subject.compareDocumentPosition(detail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it.each([["no why at all", undefined], ["a why of nothing", ""], ["a why of spaces", "   "]])(
      "with %s the title is the heading and is not said twice, nor is the target", (_what, why) => {
      render(card({ ...ASK, why }));
      expect(screen.getAllByText("Delete ~/Notes/2025")).toHaveLength(1);
      expect(screen.queryByTestId("action-subject")).toBeNull();
      cleanup();
      render(card({ ...ASK, title: "", why }));
      expect(screen.getAllByText("~/Notes/2025")).toHaveLength(1);
      expect(screen.queryByTestId("action-subject")).toBeNull();
    });

    it("a kind with its own words says none of it again: its title already names what is granted", () => {
      render(card({ kind: "desktop_app", target: "Notes", title: "Delete ~/Notes/2025", why: "Tidy the notes", detail: "" }));
      expect(screen.queryByTestId("action-subject")).toBeNull();
      expect(screen.getByTestId("action-card")).not.toHaveTextContent("Delete ~/Notes/2025");
    });
  });

  it("a title of spaces handed straight to the card is no title: the heading is the target, and so is the line under the model's", () => {
    render(card({ kind: "app", target: "com.example.App", title: "   " }));
    expect(screen.getByTestId("action-title").textContent).toBe("com.example.App");
    expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");
    cleanup();
    render(card({ kind: "app", target: "com.example.App", title: " \n ", why: "Tidy the notes", detail: "" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("Tidy the notes");
    expect(screen.getByTestId("action-subject").textContent).toBe("com.example.App");
    expect(screen.getByTestId("action-subject")).not.toHaveAttribute("lang");
  });

  it.each([["spaces", "   "], ["nothing", ""], ["no why at all", undefined]])(
    "a why of %s asks the title, else the bare target: never a blank question", (_what, why) => {
    render(card({ kind: "app", title: "Use App?", target: "com.example.App", why }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("Use App?");
    cleanup();
    render(card({ kind: "app", title: "", target: "com.example.App", why }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("com.example.App");
  });

  it("does not need Object.hasOwn, which the older WebKit the app still supports (macOS 11) does not have", () => {
    // Rendered to a string: jsdom itself calls Object.hasOwn on every DOM call, so a DOM render cannot run without it.
    const original = Object.getOwnPropertyDescriptor(Object, "hasOwn")!;
    delete (Object as { hasOwn?: unknown }).hasOwn;
    let known = "", unknown = "";
    try {
      known = renderToStaticMarkup(card({ kind: "browser_site", target: "x.com" }));
      unknown = renderToStaticMarkup(card({ kind: "toString", title: "Use it?" }));   // a key every object has is still not a kind
    } finally {
      Object.defineProperty(Object, "hasOwn", original);
    }
    expect(known).toContain("hands.title.browser_site");
    expect(unknown).toContain("Use it?");
    expect(unknown).not.toContain("hands.title.toString");
  });

  it("the server's English question says it is English (R11); the card's own words and a bare target do not", () => {
    render(card({ kind: "app", title: "Use App?" }));
    expect(screen.getByTestId("action-title")).toHaveAttribute("lang", "en");
    cleanup();
    render(card({ kind: "app", title: "", target: "com.example.App" }));
    expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");
    cleanup();
    render(card({ title: "Ignored for a known kind" }));
    expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");
  });

  it.each(["money", "app_risky", "destructive"])("a %s step draws Allow red", (permKind) => {
    render(card({ kind: "app", title: "Do it?", permKind, options: ["once"] }));
    expect(screen.getByTestId("action-allow").className).toContain("danger");
  });

  it.each(["app", "send", "shortcut", ""])("a step of kind %j does not", (permKind) => {
    render(card({ kind: "app", title: "Do it?", permKind, options: ["once"] }));
    expect(screen.getByTestId("action-allow").className).not.toContain("danger");
  });

  it("a card with no permission kind is not red either", () => {
    render(card({ kind: "app", title: "Do it?", options: ["once"] }));
    expect(screen.getByTestId("action-allow").className).not.toContain("danger");
  });

  it.each([
    ["desktop_risky", undefined, "true"], ["app", "money", "true"], ["app", "app_risky", "true"],
    ["app", "destructive", "true"], ["app", "send", "false"], ["desktop_app", undefined, "false"],
  ])("data-risky on kind %s with permission kind %s is %s: the same red as Allow", (kind, permKind, risky) => {
    render(card({ kind, title: "Do it?", permKind }));
    expect(screen.getByTestId("action-card")).toHaveAttribute("data-risky", risky);
  });

  it("a job's card names the job as the one asking; the window's card names Arslan", () => {
    render(card({ kind: "app", title: "Use App?", options: ["task", "conversation"], background: true }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
    cleanup();
    render(card({ kind: "app", title: "Use App?", options: ["task", "conversation"] }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");
  });

  it("a card the server marked background (a job's) names the job as its asker", () => {
    render(card({ kind: "desktop_app", background: true }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
  });

  it.each(["toString", "constructor", "__proto__", "hasOwnProperty", "valueOf"])(
    "a kind named %s (a key every object has) is a kind it has no words for, not a crash", (kind) => {
    render(card({ kind, title: "Use it?", target: "x", options: ["once", "conversation"] }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("Use it?");
    expect(screen.queryByText(/hands\.(scope|grant|title)\./)).toBeNull();
  });

  it("a kind it has no words for gets a neutral icon, not the terminal's", () => {
    const icon = () => document.querySelector(".lucide-terminal");
    render(card({ kind: "mac_script", detail: "tell application \"Notes\" to activate" }));
    expect(icon()).not.toBeNull();                                               // a script is a terminal-ish thing
    cleanup();
    render(card({ kind: "app", title: "Use App?" }));
    expect(icon()).toBeNull();
    expect(screen.getByTestId("action-title").parentElement?.querySelector("svg")).not.toBeNull();   // but it has an icon
  });

  it("an empty detail leaves no empty paragraph; a detail is a paragraph", () => {
    const { container } = render(card({ kind: "app", title: "Use App?", detail: "" }));
    expect(container.querySelector("p")).toBeNull();
    cleanup();
    const again = render(card({ kind: "app", title: "Use App?", detail: "Opens the inbox" }));
    expect(again.container.querySelector("p")).toHaveTextContent("Opens the inbox");
  });
});

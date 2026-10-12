/** 0.1.61 §A4: each of the four asking cards offers the frame's choices, answers with the one
 *  chosen, takes a note on No, and stays exactly as before for a frame without choices. */
import type { ReactElement } from "react";
import { describe, it, expect, vi, afterEach, type Mock } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import ActionApprovalCard from "../components/ActionApprovalCard";
import RunCommandCard from "../components/RunCommandCard";
import ScheduleGrantCard from "../components/ScheduleGrantCard";
import WorkspaceWriteCard from "../components/WorkspaceWriteCard";

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
  it("a write card offers Once / In this conversation, drops the 'rest of the session' line, answers the scope", () => {
    const onConfirm = vi.fn();
    render(<WorkspaceWriteCard callId="w1" workspace="/Users/me/Arslan" action="write_file" path="a.md"
      options={["once", "conversation"]} onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.queryByText("wswrite.scope")).toBeNull();
    fireEvent.click(screen.getByTestId("wswrite-scope-conversation"));
    fireEvent.click(screen.getByTestId("wswrite-allow"));
    expect(onConfirm).toHaveBeenCalledWith("w1", "conversation");
  });

  it("an old write card is unchanged: the session line, (callId) only", () => {
    const onConfirm = vi.fn();
    render(<WorkspaceWriteCard callId="w2" workspace="/w" action="write_file" path="a.md" onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.getByText("wswrite.scope")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("wswrite-allow"));
    expect(onConfirm.mock.calls[0]).toStrictEqual(["w2"]);
  });

  it("a schedule card says what an unattended run does, not 'for the rest of this session'", () => {
    const onConfirm = vi.fn(), onCancel = vi.fn();
    render(<ScheduleGrantCard callId="s1" name="digest" when="every: 86400" options={["once", "conversation"]}
      onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByTestId("schedule-unattended")).toHaveTextContent("schedgrant.unattended");
    expect(screen.queryByTestId("schedule-scope")).toBeNull();
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
    expect(screen.getByText("hands.scope.desktop_app")).toBeInTheDocument();  // its fixed line is true here
    expect(screen.getByTestId("action-allow").className).toContain("danger");
  });

  it("an old frame answers with no arguments, as before", () => {
    const onConfirm = vi.fn(), onCancel = vi.fn();
    render(<ActionApprovalCard kind="browser_site" target="x.com" detail="click" onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByTestId("action-allow"));
    fireEvent.click(screen.getByTestId("action-deny"));
    expect(onConfirm.mock.calls[0]).toStrictEqual([]);
    expect(onCancel.mock.calls[0]).toStrictEqual([]);
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
  /** the arguments of a yes on a card with no choices: what an old card has always sent */
  oldYesArgs: unknown[];
}

const CARDS: Row[] = [
  { name: "run a command", choices: "runcmd-scope", note: "runcmd-note", allow: "runcmd-run", deny: "runcmd-cancel",
    mount: (p) => <RunCommandCard callId="r1" pretty="rm a" {...p} />,
    yesArgs: (scope) => ["r1", false, scope], noArgs: (note) => (note ? ["r1", note] : ["r1"]), oldYesArgs: ["r1", false] },
  { name: "write", choices: "wswrite-scope", note: "wswrite-note", allow: "wswrite-allow", deny: "wswrite-deny",
    mount: (p) => <WorkspaceWriteCard callId="w1" workspace="/w" action="write_file" path="a.md" {...p} />,
    yesArgs: (scope) => ["w1", scope], noArgs: (note) => (note ? ["w1", note] : ["w1"]), oldYesArgs: ["w1"] },
  { name: "schedule", choices: "schedule-choice", note: "schedule-note", allow: "schedule-allow", deny: "schedule-deny",
    mount: (p) => <ScheduleGrantCard callId="s1" name="digest" when="every: 86400" {...p} />,
    yesArgs: (scope) => ["s1", scope], noArgs: (note) => (note ? ["s1", note] : ["s1"]), oldYesArgs: ["s1"] },
  { name: "action", choices: "action-scope", note: "action-note", allow: "action-allow", deny: "action-deny",
    mount: (p) => <ActionApprovalCard kind="app" target="com.example.App" detail="" title="Use App?" {...p} />,
    yesArgs: (scope) => [scope], noArgs: (note) => (note ? [note] : []), oldYesArgs: [] },
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
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.yesArgs("once"));
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

  it.each([["no options", undefined], ["an empty options list", [] as string[]]])(
    "a card with %s offers neither a choice nor a note: a No there would lose the note", (_what, options) => {
    const { onConfirm, onCancel } = spies();
    render(row.mount({ options, onConfirm, onCancel }));
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByTestId(`${row.note}-open`)).toBeNull();
    expect(screen.queryByText("kit.noteLink")).toBeNull();
    fireEvent.click(screen.getByTestId(row.allow));
    expect(onConfirm.mock.calls.at(-1)).toStrictEqual(row.oldYesArgs);          // answered exactly as an old card is
  });

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

describe("the action card's words and its red", () => {
  const card = (p: Partial<Parameters<typeof ActionApprovalCard>[0]>) => (
    <ActionApprovalCard kind="desktop_app" target="Notes" detail="click" onConfirm={vi.fn()} onCancel={vi.fn()} {...p} />);

  it("a known kind's fixed-scope line yields to a real choice, and stays when there is none to pick", () => {
    const { rerender } = render(card({ options: ["once", "conversation"] }));
    expect(screen.queryByText("hands.scope.desktop_app")).toBeNull();          // two choices say it themselves
    rerender(card({ options: ["once"] }));
    expect(screen.getByText("hands.scope.desktop_app")).toBeInTheDocument();   // one choice: the fixed line is true
    rerender(card({}));
    expect(screen.getByText("hands.scope.desktop_app")).toBeInTheDocument();   // an old frame: as before
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

  it("a job's card names the job as the one asking; the window's card names Arslan", () => {
    render(card({ kind: "app", title: "Use App?", options: ["task", "conversation"], background: true }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
    cleanup();
    render(card({ kind: "app", title: "Use App?", options: ["task", "conversation"] }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");
  });

  it("an old frame names its asker as before: looking is Arslan, anything else is a job", () => {
    render(card({ kind: "desktop_look" }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");
    cleanup();
    render(card({ kind: "desktop_app", background: false }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
  });
});

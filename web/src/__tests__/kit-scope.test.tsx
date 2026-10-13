/** 0.1.61 §A4: the card's choices, the optional note on No, and the keys around them. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, createEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import {
  ANSWER_GUARD_MS, AskCard, AskQueue, CARD_MS, DeclineNote, Dialog, ScopeChoice, scopeToSend, useAnswerKeys, visibleScopes,
} from "../components/kit";
import LeftoverSheet from "../components/projects/LeftoverSheet";

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("ScopeChoice", () => {
  it("shows exactly the card's options in its order, the always one with its literal scope", () => {
    const onChange = vi.fn();
    render(<ScopeChoice options={["task", "conversation", "always"]} value="task" alwaysLabel="WeChat" onChange={onChange} />);
    expect(screen.getByRole("radiogroup", { name: "kit.scope.label" })).toBeInTheDocument();
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios.map((r) => r.value)).toEqual(["task", "conversation", "always"]);
    expect(radios.map((r) => r.checked)).toEqual([true, false, false]);
    expect(screen.getByLabelText('kit.scope.always:{"label":"WeChat"}')).toBe(radios[2]);
    fireEvent.click(radios[1]);
    expect(onChange).toHaveBeenCalledWith("conversation");
  });

  it("never draws an id it does not know, nor an Always without its scope; one choice draws nothing", () => {
    render(<ScopeChoice options={["once", "forever", "always"]} value="once" onChange={vi.fn()} />);
    expect(screen.queryByRole("radiogroup")).toBeNull();          // "forever" unknown, "always" has no label
    expect(visibleScopes(["once", "forever", "always"], "")).toEqual(["once"]);
  });

  it("two cards side by side keep their own choice", () => {
    render(<><ScopeChoice options={["once", "conversation"]} value="once" onChange={vi.fn()} testId="a" />
      <ScopeChoice options={["once", "conversation"]} value="conversation" onChange={vi.fn()} testId="b" /></>);
    expect((screen.getByTestId("a-once") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("b-conversation") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("a-once") as HTMLInputElement).name).not.toBe((screen.getByTestId("b-once") as HTMLInputElement).name);
  });

  it("a yes is sent with a choice the card offered, never another", () => {
    expect(scopeToSend(["once", "conversation"], "conversation")).toBe("conversation");
    expect(scopeToSend(["once", "conversation"], "always", "x")).toBe("once");        // not offered
    expect(scopeToSend(["task", "always"], "always", "")).toBe("task");               // Always without its scope
    expect(scopeToSend(undefined, "always")).toBeUndefined();                          // an old card: no scope
  });

  it("the fallback is the first option the card SHOWS: never a hidden id, never Always unasked", () => {
    expect(scopeToSend(["always", "once"], undefined, "")).toBe("once");                     // Always first, but without its scope
    expect(scopeToSend(["forever", "task", "always"], "forever", "")).toBe("task");          // an id the kit does not know
    expect(scopeToSend(["always", "once"], undefined, "WeChat")).toBe("once");               // Always shown, still never the default
    expect(scopeToSend(["always", "once"], "always", "WeChat")).toBe("always");              // only what the person picked
    expect(scopeToSend(["always"], undefined, "WeChat")).toBeUndefined();                    // a lone Always is not sent unasked
    expect(scopeToSend(["always"], "always", "WeChat")).toBe("always");
  });

  it("an Always label of spaces is no label; an id the frame repeats is shown once; the label is shown trimmed", () => {
    expect(visibleScopes(["once", "always"], "   ")).toEqual(["once"]);
    expect(scopeToSend(["always", "task"], "always", "   ")).toBe("task");
    expect(visibleScopes(["once", "task", "once", "task"], "")).toEqual(["once", "task"]);
    render(<ScopeChoice options={["once", "once", "always"]} value="once" alwaysLabel="  WeChat " onChange={vi.fn()} />);
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByLabelText('kit.scope.always:{"label":"WeChat"}')).toBeInTheDocument();
  });

  it("what is ticked is what a yes sends; a lone Always is drawn, and never ticked for the person", () => {
    const ticked = () => (screen.getAllByRole("radio") as HTMLInputElement[]).map((r) => [r.value, r.checked]);
    // a value the card does not show (a stale one, or none yet) ticks the choice a yes would send
    render(<ScopeChoice options={["once", "conversation"]} value="always" onChange={vi.fn()} />);
    expect(ticked()).toEqual([["once", true], ["conversation", false]]);
    cleanup();
    render(<ScopeChoice options={["always", "once"]} value="" alwaysLabel="WeChat" onChange={vi.fn()} />);
    expect(ticked()).toEqual([["always", false], ["once", true]]);
    cleanup();
    render(<ScopeChoice options={["always"]} value="" alwaysLabel="WeChat" onChange={vi.fn()} />);
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();                       // seen, not slipped in
    expect(ticked()).toEqual([["always", false]]);
  });
});

describe("DeclineNote", () => {
  it("is a link until opened; Say no sends the trimmed note", () => {
    const onDecline = vi.fn();
    render(<DeclineNote onDeclineWithNote={onDecline} />);
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByText("kit.noteLink"));
    const box = screen.getByRole("textbox", { name: "kit.notePlaceholder" });
    expect(box).toHaveFocus();
    fireEvent.change(box, { target: { value: "  use Bear instead " } });
    fireEvent.click(screen.getByText("kit.noteSend"));
    expect(onDecline).toHaveBeenCalledWith("use Bear instead");
  });

  it("on a card: ⌘⏎ and ⏎ in the note say No with it; esc closes the line and keeps the text; neither reaches the card", () => {
    const allow = vi.fn(), decline = vi.fn(), note = vi.fn();
    render(<AskCard who="w" title="t" onAllow={allow} onDecline={decline} extra={<DeclineNote onDeclineWithNote={note} />} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "weekly is enough" } });
    fireEvent.keyDown(box, { key: "Enter", metaKey: true });
    expect(note).toHaveBeenLastCalledWith("weekly is enough");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(note).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("kit.noteLink")).toHaveFocus();
    expect(allow).not.toHaveBeenCalled();
    expect(decline).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("kit.noteLink"));
    expect(screen.getByRole("textbox")).toHaveValue("weekly is enough");      // not lost
  });

  it("an input method's ⏎ in the note sends nothing", () => {
    const note = vi.fn();
    render(<DeclineNote onDeclineWithNote={note} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", isComposing: true } as never);
    expect(note).not.toHaveBeenCalled();
  });

  it("⏎ and ⌘⏎ send the note trimmed, as the button does", () => {
    const note = vi.fn();
    render(<DeclineNote onDeclineWithNote={note} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "  use Bear instead " } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(note).toHaveBeenLastCalledWith("use Bear instead");
    fireEvent.keyDown(box, { key: "Enter", metaKey: true });
    expect(note).toHaveBeenLastCalledWith("use Bear instead");
    expect(note).toHaveBeenCalledTimes(2);
  });

  it("⏎ and ⌘⏎ are taken from the browser (its form would send the note a second time); typing is left alone", () => {
    const note = vi.fn();
    render(<DeclineNote onDeclineWithNote={note} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    const box = screen.getByRole("textbox");
    expect(fireEvent.keyDown(box, { key: "Enter" })).toBe(false);                    // false: the default was prevented
    expect(fireEvent.keyDown(box, { key: "Enter", metaKey: true })).toBe(false);
    expect(fireEvent.keyDown(box, { key: "a" })).toBe(true);                         // an ordinary key is not ours
    expect(note).toHaveBeenCalledTimes(2);
  });

  it("a held ⏎ or ⌘⏎ says No once: its repeats send nothing, and are still taken from the browser", () => {
    const note = vi.fn();
    render(<DeclineNote onDeclineWithNote={note} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "hold" } });
    fireEvent.keyDown(box, { key: "Enter" });
    // a repeat that is not cancelled would submit the form again in a browser, so it is cancelled, not just ignored
    expect(fireEvent.keyDown(box, { key: "Enter", repeat: true })).toBe(false);
    expect(fireEvent.keyDown(box, { key: "Enter", repeat: true })).toBe(false);
    expect(fireEvent.keyDown(box, { key: "Enter", metaKey: true, repeat: true })).toBe(false);
    expect(note).toHaveBeenCalledTimes(1);
    expect(note).toHaveBeenLastCalledWith("hold");
  });

  it("the Say no button is part of the line: ⌘⏎ and esc on it are the line's keys, not the card's", () => {
    const allow = vi.fn(), decline = vi.fn(), note = vi.fn();
    render(<AskCard who="w" title="t" onAllow={allow} onDecline={decline} extra={<DeclineNote onDeclineWithNote={note} />} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "no, because" } });
    const send = screen.getByText("kit.noteSend");
    fireEvent.keyDown(send, { key: "Enter", metaKey: true });
    expect(allow).not.toHaveBeenCalled();
    expect(note).toHaveBeenLastCalledWith("no, because");
    fireEvent.keyDown(send, { key: "Escape" });
    expect(decline).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();                                // the line closed ...
    fireEvent.click(screen.getByText("kit.noteLink"));
    expect(screen.getByRole("textbox")).toHaveValue("no, because");                  // ... and kept the text
  });

  it("an input method's committing key (WebKit: keyCode 229, isComposing false) does nothing on the note or on the card", () => {
    const allow = vi.fn(), decline = vi.fn(), note = vi.fn();
    render(<AskCard who="w" title="t" onAllow={allow} onDecline={decline} extra={<DeclineNote onDeclineWithNote={note} />} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    const box = screen.getByRole("textbox");
    fireEvent.keyDown(box, { key: "Enter", keyCode: 229 });
    fireEvent.keyDown(box, { key: "Enter", metaKey: true, keyCode: 229 });
    fireEvent.keyDown(box, { key: "Escape", keyCode: 229 });
    expect(note).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox")).toBeInTheDocument();                         // esc did not close the line either
    expect(allow).not.toHaveBeenCalled();
    expect(decline).not.toHaveBeenCalled();
    fireEvent.keyDown(document.body, { key: "Enter", metaKey: true, keyCode: 229 });   // the card's own keys
    fireEvent.keyDown(document.body, { key: "Escape", keyCode: 229 });
    expect(allow).not.toHaveBeenCalled();
    expect(decline).not.toHaveBeenCalled();
  });

  it("Say no is a submit the page never follows", () => {
    const note = vi.fn();
    render(<DeclineNote onDeclineWithNote={note} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    const form = screen.getByTestId("ask-note");
    const submit = createEvent.submit(form);
    fireEvent(form, submit);
    expect(submit.defaultPrevented).toBe(true);
    expect(note).toHaveBeenCalledTimes(1);
  });

  it("a card that appears does not take focus from the composer", () => {
    render(<textarea data-testid="composer" />);
    const composer = screen.getByTestId("composer");
    composer.focus();
    render(<AskCard who="w" title="t" onAllow={vi.fn()} onDecline={vi.fn()} extra={<DeclineNote onDeclineWithNote={vi.fn()} />} />);
    expect(composer).toHaveFocus();
  });

  it("the link is a plain button: the line replaces it, so it claims no expanded state", () => {
    render(<DeclineNote onDeclineWithNote={vi.fn()} />);
    expect(screen.getByText("kit.noteLink")).not.toHaveAttribute("aria-expanded");
  });

  it("a busy card's note sends nothing, by key, by button or by submit; the text waits for it", () => {
    const note = vi.fn();
    const { rerender } = render(<DeclineNote disabled onDeclineWithNote={note} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "wait" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.keyDown(box, { key: "Enter", metaKey: true });
    fireEvent.click(screen.getByText("kit.noteSend"));
    fireEvent.submit(screen.getByTestId("ask-note"));
    expect(note).not.toHaveBeenCalled();
    expect(screen.getByText("kit.noteSend")).toBeDisabled();
    rerender(<DeclineNote onDeclineWithNote={note} />);
    expect(screen.getByText("kit.noteSend")).toBeEnabled();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(note).toHaveBeenCalledTimes(1);
    expect(note).toHaveBeenLastCalledWith("wait");
  });
});

describe("a queue of cards", () => {
  it("‹ › to the next card does not carry an opened note, or what was typed in it, along", () => {
    render(<AskQueue items={["a", "b"].map((k) => ({ key: k, render: (q) => (
      <AskCard who="w" title={`card ${k}`} queue={q} onAllow={vi.fn()} onDecline={vi.fn()}
        extra={<DeclineNote onDeclineWithNote={vi.fn()} />} />) }))} />);
    fireEvent.click(screen.getByText("kit.noteLink"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "for card a" } });
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect(screen.getByRole("heading")).toHaveTextContent("card b");
    expect(screen.queryByRole("textbox")).toBeNull();                                // b's note starts closed ...
    fireEvent.click(screen.getByText("kit.noteLink"));
    expect(screen.getByRole("textbox")).toHaveValue("");                             // ... and empty
  });

  /** Three cards of one kind: the card is re-mounted per ask, so its ‹ › are new buttons each time. */
  const queueOf3 = () => (
    <AskQueue items={["a", "b", "c"].map((k) => ({ key: k, render: (q) => (
      <AskCard who="w" title={`card ${k}`} queue={q} onAllow={vi.fn()} onDecline={vi.fn()} />) }))} />
  );

  it("paging from the keyboard keeps focus on the button that was pressed, on the next card too", async () => {
    const user = userEvent.setup();
    render(queueOf3());
    screen.getByLabelText("kit.next").focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading")).toHaveTextContent("card b");
    expect(screen.getByLabelText("kit.next")).toHaveFocus();                         // the new card's button, not <body>
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading")).toHaveTextContent("card c");
    expect(screen.getByLabelText("kit.next")).toHaveFocus();
    screen.getByLabelText("kit.previous").focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading")).toHaveTextContent("card b");
    expect(screen.getByLabelText("kit.previous")).toHaveFocus();                     // ‹ stays ‹
  });

  it("a click that did not focus a nav button does not pull focus to one", () => {
    render(<><textarea data-testid="composer" />{queueOf3()}</>);
    const composer = screen.getByTestId("composer");
    composer.focus();
    fireEvent.click(screen.getByLabelText("kit.next"));                              // as in Safari: a click that focuses nothing
    expect(screen.getByRole("heading")).toHaveTextContent("card b");
    expect(composer).toHaveFocus();
  });
});

describe("the card's keys and a text field", () => {
  /** Which focused elements OUTSIDE the card keep ⌘⏎ from allowing it (the composer is one of them). */
  const outside = [
    { name: "a textarea (the composer)", html: "<textarea></textarea>", blocks: true },
    { name: 'an <input type="text"> (the composer)', html: '<input type="text">', blocks: true },
    { name: 'an <input type="search">', html: '<input type="search">', blocks: true },
    { name: 'an <input type="number">', html: '<input type="number">', blocks: true },
    { name: 'an <input type="email">', html: '<input type="email">', blocks: true },
    { name: 'an <input type="password">', html: '<input type="password">', blocks: true },
    { name: "a contenteditable (a span inside it)", html: '<div contenteditable="true"><span id="hit">x</span></div>', blocks: true },
    { name: 'a contenteditable="plaintext-only"', html: '<div contenteditable="plaintext-only"><span id="hit">x</span></div>', blocks: true },
    { name: 'a role="textbox"', html: '<div role="textbox" tabindex="0" id="hit"></div>', blocks: true },
    { name: 'a role="combobox"', html: '<div role="combobox" tabindex="0" id="hit"></div>', blocks: true },
    { name: "a contenteditable with no value", html: '<div contenteditable><span id="hit">x</span></div>', blocks: true },
    { name: 'a contenteditable=""', html: '<div contenteditable=""><span id="hit">x</span></div>', blocks: true },
    { name: "a checkbox", html: '<input type="checkbox">', blocks: false },
    { name: "a radio", html: '<input type="radio">', blocks: false },
    { name: "a button", html: "<button>b</button>", blocks: false },
    { name: "a select", html: "<select></select>", blocks: false },
    // every other <input> that is a control, not a field: each entry of the list is pinned
    ...["button", "submit", "reset", "range", "color", "file", "image"].map((type) => (
      { name: `an <input type="${type}">`, html: `<input type="${type}">`, blocks: false })),
  ].map((r) => ({ ...r, verdict: r.blocks ? "never allows it; esc there still declines" : "still allows it" }));

  it.each(outside)("⌘⏎ in $name outside the card $verdict", ({ html, blocks }) => {
    const allow = vi.fn(), decline = vi.fn();
    render(<><AskCard who="w" title="t" onAllow={allow} onDecline={decline} />
      <div data-testid="outside" dangerouslySetInnerHTML={{ __html: html }} /></>);
    const host = screen.getByTestId("outside");
    const field = host.querySelector("#hit") ?? host.firstElementChild!;
    fireEvent.keyDown(field, { key: "Enter", metaKey: true });
    expect(allow).toHaveBeenCalledTimes(blocks ? 0 : 1);
    if (blocks) {
      fireEvent.keyDown(field, { key: "Escape" });
      expect(decline).toHaveBeenCalledTimes(1);
    }
  });

  it("a field on the card itself (a key it asks for) and a radio still allow with ⌘⏎", () => {
    const allow = vi.fn();
    render(<AskCard who="w" title="t" onAllow={allow} onDecline={vi.fn()}
      detail={<><input data-testid="own-key" type="password" /><input data-testid="pick" type="radio" /></>} />);
    fireEvent.keyDown(screen.getByTestId("own-key"), { key: "Enter", metaKey: true });
    fireEvent.keyDown(screen.getByTestId("pick"), { key: "Enter", metaKey: true });
    expect(allow).toHaveBeenCalledTimes(2);
  });

  it("the ring's whole is thirty minutes", () => {
    expect(CARD_MS).toBe(30 * 60 * 1000);
  });

  it("a held key answers one card: its repeats never reach the card that moves up, even after the answer guard has run out", () => {
    vi.useFakeTimers();
    const answered: string[] = [], declined: string[] = [];
    function Host() {
      const [keys, setKeys] = useState(["a", "b", "c", "d"]);
      const leave = (k: string) => setKeys((all) => all.filter((x) => x !== k));
      return <AskQueue items={keys.map((k) => ({ key: k, render: (q) => (
        <AskCard who="w" title={`card ${k}`} queue={q}
          onAllow={() => { answered.push(k); leave(k); }} onDecline={() => { declined.push(k); leave(k); }} />) }))} />;
    }
    render(<Host />);
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    act(() => { vi.advanceTimersByTime(ANSWER_GUARD_MS); });             // held past the guard: only the repeat flag holds the repeats back now
    fireEvent.keyDown(window, { key: "Enter", metaKey: true, repeat: true });
    fireEvent.keyDown(window, { key: "Enter", metaKey: true, repeat: true });
    expect(answered).toEqual(["a"]);
    fireEvent.keyDown(window, { key: "Escape" });
    act(() => { vi.advanceTimersByTime(ANSWER_GUARD_MS); });
    fireEvent.keyDown(window, { key: "Escape", repeat: true });
    fireEvent.keyDown(window, { key: "Escape", repeat: true });
    expect(declined).toEqual(["b"]);
  });

  it("focus in ANOTHER card or dialog: ⌘⏎ and esc are that surface's keys, so neither answers the top card", () => {
    const a = vi.fn(), aNo = vi.fn(), b = vi.fn(), bNo = vi.fn();
    render(<>
      <AskCard testId="A" who="a" title="a" onAllow={a} onDecline={aNo} detail={<input type="radio" data-testid="radioA" />} />
      <AskCard testId="B" who="b" title="b" onAllow={b} onDecline={bNo} detail={<input type="radio" data-testid="radioB" />} />
      <div role="dialog" aria-label="a popover that is not the kit's"><button data-testid="popover-button">m</button></div>
    </>);
    for (const id of ["radioA", "popover-button"]) {                              // the older card, and a plain popover
      fireEvent.keyDown(screen.getByTestId(id), { key: "Enter", metaKey: true });
      fireEvent.keyDown(screen.getByTestId(id), { key: "Escape" });
    }
    expect(b).not.toHaveBeenCalled();
    expect(bNo).not.toHaveBeenCalled();
    expect(a).not.toHaveBeenCalled();                                              // A is not the top layer either
    expect(aNo).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByTestId("radioB"), { key: "Enter", metaKey: true });   // focus in the top card itself
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("a native <dialog>, and the bare panel of another dialog (focus on it, nothing inside), are other surfaces too", () => {
    const b = vi.fn(), bNo = vi.fn();
    render(<>
      <AskCard who="b" title="b" onAllow={b} onDecline={bNo} />
      <dialog open data-testid="native"><button data-testid="native-button">n</button></dialog>
      <div role="dialog" tabIndex={-1} data-testid="bare-panel" />
    </>);
    for (const id of ["native", "native-button", "bare-panel"]) {
      fireEvent.keyDown(screen.getByTestId(id), { key: "Enter", metaKey: true });
      fireEvent.keyDown(screen.getByTestId(id), { key: "Escape" });
    }
    expect(b).not.toHaveBeenCalled();
    expect(bNo).not.toHaveBeenCalled();
  });

  it("a surface that has no panel (null) takes the keys from anywhere, a dialog included: it cannot tell which is another", () => {
    const allow = vi.fn(), decline = vi.fn();
    function Bare() {
      useAnswerKeys(true, { onAllow: allow, onDecline: decline }, null);
      return <div role="dialog"><button data-testid="inside-a-dialog">x</button></div>;
    }
    render(<Bare />);
    fireEvent.keyDown(screen.getByTestId("inside-a-dialog"), { key: "Enter", metaKey: true });
    fireEvent.keyDown(screen.getByTestId("inside-a-dialog"), { key: "Escape" });
    expect(allow).toHaveBeenCalledTimes(1);
    expect(decline).toHaveBeenCalledTimes(1);
  });

  it("a surface that has no panel says so with null: typing still never answers it, a radio does", () => {
    const allow = vi.fn();
    function Bare() {
      useAnswerKeys(true, { onAllow: allow }, null);
      return <><textarea data-testid="field" /><input type="radio" data-testid="pick" /></>;
    }
    render(<Bare />);
    fireEvent.keyDown(screen.getByTestId("field"), { key: "Enter", metaKey: true });
    expect(allow).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByTestId("pick"), { key: "Enter", metaKey: true });
    expect(allow).toHaveBeenCalledTimes(1);
  });

  it("is a type error to leave `within` out, so no caller forgets where its surface is", () => {
    function Forgot() {
      // @ts-expect-error — `within` is required (null when there is none): `tsc --noEmit` fails the day it is optional again
      useAnswerKeys(false, {});
      return null;
    }
    expect(() => render(<Forgot />)).not.toThrow();
  });
});

/** The same rule for a Dialog with onSubmit: its own fields submit with ⌘⏎, the composer behind it never does. */
describe("a dialog's keys and a text field", () => {
  it("⌘⏎ typed in a field of the dialog itself submits it (the leftover sheet's note)", () => {
    const onConfirm = vi.fn();
    render(<LeftoverSheet level="L1" next="L2" open={[{ id: "a", text: "first" }]} onCancel={vi.fn()} onConfirm={onConfirm} />);
    const field = screen.getByTestId("leftover-note");
    fireEvent.change(field, { target: { value: "not needed" } });
    fireEvent.keyDown(field, { key: "Enter", metaKey: true });
    expect(onConfirm).toHaveBeenCalledWith("move", "not needed");
  });

  it("⌘⏎ typed in a field outside an open dialog (the composer) never submits it; esc there still closes it", () => {
    const onSubmit = vi.fn(), onClose = vi.fn();
    render(<><textarea data-testid="composer" />
      <Dialog open title="d" onClose={onClose} onSubmit={onSubmit}><input data-testid="inside" /></Dialog></>);
    fireEvent.keyDown(screen.getByTestId("composer"), { key: "Enter", metaKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByTestId("inside"), { key: "Enter", metaKey: true });          // its own field does
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByTestId("composer"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

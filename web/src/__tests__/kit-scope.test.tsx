/** 0.1.61 §A4: the card's choices, the optional note on No, and the keys around them. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import { AskCard, CARD_MS, DeclineNote, ScopeChoice, scopeToSend, visibleScopes } from "../components/kit";

afterEach(() => cleanup());

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
});

describe("the card's keys and a text field", () => {
  it("⌘⏎ typed in a field outside the card (the composer) never allows; esc there still declines", () => {
    const allow = vi.fn(), decline = vi.fn();
    render(<><textarea data-testid="composer" /><AskCard who="w" title="t" onAllow={allow} onDecline={decline} /></>);
    fireEvent.keyDown(screen.getByTestId("composer"), { key: "Enter", metaKey: true });
    expect(allow).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByTestId("composer"), { key: "Escape" });
    expect(decline).toHaveBeenCalledTimes(1);
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
});

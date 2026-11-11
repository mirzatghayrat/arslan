// HOOK-4, #853 review: a hook's command line shows what the shell will read. A line break is a muted marker and a real
// break on a box that keeps its lines; every other control character, bidi controls included, is an escape. Every
// command is invented. Control characters are built from code points, so this file holds none of them itself.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "../i18n";
import { CommandText } from "../components/capabilities/HooksRow";
import { commandParts, escapeOf } from "../lib/commandText";

afterEach(cleanup);

const ch = (cp: number) => String.fromCodePoint(cp);
const LF = ch(0x0a), TAB = ch(0x09), CR = ch(0x0d), ESC = ch(0x1b), NEL = ch(0x85), DEL = ch(0x7f);
const RLO = ch(0x202e), RLI = ch(0x2067), LSEP = ch(0x2028);
const MARKER = String.fromCodePoint(0x23ce);
const BACKSLASH = String.fromCodePoint(0x5c);

describe("commandParts", () => {
  it("leaves an ordinary command as one plain part", () => {
    expect(commandParts("git status --short -- ./src")).toEqual([{ kind: "text", text: "git status --short -- ./src" }]);
    expect(commandParts("")).toEqual([]);
  });

  it("splits at each line break, keeping both lines", () => {
    expect(commandParts(`true${LF}rm -rf ~/x`)).toEqual([
      { kind: "text", text: "true" }, { kind: "break" }, { kind: "text", text: "rm -rf ~/x" }]);
    expect(commandParts(`a${LF}${LF}`)).toEqual([{ kind: "text", text: "a" }, { kind: "break" }, { kind: "break" }]);
  });

  it("makes tab, CR, ESC, DEL, C1, separators and bidi controls escapes", () => {
    const escaped = (cp: number) => ({ kind: "escape", text: escapeOf(cp) });
    expect(commandParts(`a${TAB}b${CR}${LF}${ESC}[2J${DEL}${NEL}${LSEP}${RLO}${RLI}`)).toEqual([
      { kind: "text", text: "a" }, escaped(0x09), { kind: "text", text: "b" }, escaped(0x0d), { kind: "break" },
      escaped(0x1b), { kind: "text", text: "[2J" }, escaped(0x7f), escaped(0x85), escaped(0x2028), escaped(0x202e),
      escaped(0x2067)]);
  });

  it.each([[0x00, "x00"], [0x09, "x09"], [0x1b, "x1B"], [0x9f, "x9F"], [0x202e, "u202E"], [0x2069, "u2069"]])(
    "escapes code point %i as a backslash and %s", (cp, tail) => {
      expect(escapeOf(cp)).toBe(BACKSLASH + tail);
    });

  it("leaves visible text alone, other scripts and emoji included", () => {
    const text = "echo 'héllo, мир, 世界 🚀' | wc -c";
    expect(commandParts(text)).toEqual([{ kind: "text", text }]);
  });
});

describe("CommandText", () => {
  it("a two-line shell command shows both lines and the marker, on a box that keeps its lines", () => {
    render(<CommandText text={`true${LF}rm -rf ~/x`} />);
    const box = screen.getByTestId("command-text");
    expect(box).toHaveClass("whitespace-pre-wrap");
    expect(box.textContent).toBe(`true${MARKER}${LF}rm -rf ~/x`);
    const marker = screen.getByTestId("command-break");
    expect(marker.textContent).toBe(MARKER);
    expect(marker).toHaveClass("text-muted-foreground");
  });

  it("a bidi override is shown, never applied", () => {
    render(<CommandText text={`echo ${RLO}txt.exe`} />);
    const box = screen.getByTestId("command-text");
    expect(box.textContent).toBe(`echo ${BACKSLASH}u202Etxt.exe`);
    expect(box.textContent).not.toContain(RLO);
    expect(screen.getByTestId("command-escape").textContent).toBe(`${BACKSLASH}u202E`);
  });

  it("tab, CR and ESC are escapes too", () => {
    render(<CommandText text={`a${TAB}b${CR}c${ESC}d`} />);
    expect(screen.getByTestId("command-text").textContent).toBe(
      `a${BACKSLASH}x09b${BACKSLASH}x0Dc${BACKSLASH}x1Bd`);
    expect(screen.getAllByTestId("command-escape")).toHaveLength(3);
  });

  it("an ordinary command is unchanged", () => {
    render(<CommandText text="python3 ./hooks/check.py --strict" />);
    const box = screen.getByTestId("command-text");
    expect(box.textContent).toBe("python3 ./hooks/check.py --strict");
    expect(screen.queryByTestId("command-break")).toBeNull();
    expect(screen.queryByTestId("command-escape")).toBeNull();
  });

  it("what shows nothing still gets Escaped's marker", () => {
    render(<CommandText text={`a${ch(0x200b)}b`} />);
    expect(screen.getByTestId("command-text").textContent).toBe("aU+200Bb");
  });
});

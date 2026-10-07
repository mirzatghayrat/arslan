/** 0.1.55 decision 1: the risk line comes from the script, not from the model's summary. */
import { describe, it, expect } from "vitest";
import { appleScriptRisk, blankLiterals } from "../lib/scriptRisk";

describe("appleScriptRisk", () => {
  it("a read-only script has no risk line", () => {
    expect(appleScriptRisk('tell application "Notes"\n  set ms to (notes whose name = "Hands 冒烟")\n  return count of ms\nend tell')).toBeNull();
  });
  it("names delete and its line", () => {
    const r = appleScriptRisk('tell application "Notes"\n  delete (notes whose name = "Hands 冒烟")\nend tell');
    expect(r).toMatchObject({ effects: ["delete"], lines: [2], words: ["delete"], unknown: false });
  });
  it("a word inside a string or a comment does not count", () => {
    expect(appleScriptRisk('tell application "Notes" to get (notes whose name = "delete me, send it")\n-- delete later\n(* move *)')).toBeNull();
  });
  it("finds every effect: shell, send, create, modify, save, quit", () => {
    const r = appleScriptRisk([
      'do shell script "rm -rf ~/x"',
      'tell application "Mail" to send theMessage',
      'make new note with properties {name:"a"}',
      'set body of n to "hello"',
      'save front document',
      'quit',
    ].join("\n"))!;
    expect(r.effects).toEqual(["shell", "send", "create", "modify", "save", "quit"]);
    expect(r.lines).toEqual([1, 2, 3, 4, 5, 6]);
  });
  it("cannot see through run script / raw events: says so", () => {
    expect(appleScriptRisk('run script (read file "x")')).toMatchObject({ effects: [], unknown: true });
    expect(appleScriptRisk("tell application \"Finder\" to «event coredelo» x")?.unknown).toBe(true);
  });
  it("blanking keeps line numbers", () => {
    expect(blankLiterals('a "x\ny" b').split("\n")).toHaveLength(2);
  });
});

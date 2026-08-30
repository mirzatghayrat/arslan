/**
 * Voice output core (V1). The segmenter is the piece that has to be right — it
 * decides when the voice speaks, and a wrong boundary either stutters (speaks a
 * half-word) or lags (waits for the whole answer). The synthesis wrapper is a
 * thin capability-guarded edge, tested against a stubbed speechSynthesis.
 */
import { describe, test, expect, beforeEach, vi } from "vitest";
import {
  createSentenceFeeder,
  createSpeaker,
  speechSupported,
  voiceLangFor,
} from "../lib/speech";

describe("sentence feeder", () => {
  test("emits a sentence only once its terminator arrives", () => {
    const f = createSentenceFeeder();
    expect(f.push("Look at ")).toEqual([]);      // no terminator yet — hold it
    expect(f.push("your desktop.")).toEqual(["Look at your desktop."]);
  });

  test("a chunk splitting a word does not speak twice", () => {
    const f = createSentenceFeeder();
    expect(f.push("hel")).toEqual([]);
    expect(f.push("lo.")).toEqual(["hello."]);
  });

  test("several sentences in one chunk all come out, in order", () => {
    const f = createSentenceFeeder();
    expect(f.push("One. Two! Three?")).toEqual(["One.", "Two!", "Three?"]);
  });

  test("CJK terminators break too", () => {
    const f = createSentenceFeeder();
    expect(f.push("你好。在吗?")).toEqual(["你好。", "在吗?"]);
  });

  test("newlines are boundaries", () => {
    const f = createSentenceFeeder();
    expect(f.push("line one\nline two\n")).toEqual(["line one", "line two"]);
  });

  test("flush returns the unterminated tail, once", () => {
    const f = createSentenceFeeder();
    f.push("a complete one. and a trailing bit");
    expect(f.flush()).toEqual(["and a trailing bit"]);
    expect(f.flush()).toEqual([]);               // nothing left the second time
  });

  test("whitespace-only tail is not spoken", () => {
    const f = createSentenceFeeder();
    f.push("done.   ");
    expect(f.flush()).toEqual([]);
  });
});

describe("voiceLangFor", () => {
  test.each([
    ["zh", "zh-CN"], ["ja", "ja-JP"], ["de", "de-DE"],
    ["fr", "fr-FR"], ["es", "es-ES"], ["en", "en-US"],
    ["", "en-US"], [undefined, "en-US"],
  ])("%s -> %s", (input, expected) => {
    expect(voiceLangFor(input as string)).toBe(expected);
  });
});

describe("the speaker, against a stubbed synthesizer", () => {
  let spoken: string[];
  beforeEach(() => {
    spoken = [];
    (globalThis as any).SpeechSynthesisUtterance = class {
      text: string; lang = "";
      constructor(t: string) { this.text = t; }
    };
    (globalThis as any).window = {
      speechSynthesis: {
        speak: (u: any) => spoken.push(u.text),
        cancel: vi.fn(),
      },
      SpeechSynthesisUtterance: (globalThis as any).SpeechSynthesisUtterance,
    };
  });

  test("speaks each completed sentence as it streams", () => {
    const sp = createSpeaker("en-US");
    sp.feed("Hi there. ");
    sp.feed("Reading now.");
    expect(spoken).toEqual(["Hi there.", "Reading now."]);
  });

  test("end() speaks the unterminated tail", () => {
    const sp = createSpeaker("en-US");
    sp.feed("a finished one. a dangling tail");
    expect(spoken).toEqual(["a finished one."]);
    sp.end();
    expect(spoken).toEqual(["a finished one.", "a dangling tail"]);
  });

  test("cancel stops the synthesizer", () => {
    const sp = createSpeaker("en-US");
    sp.cancel();
    expect((window.speechSynthesis.cancel as any)).toHaveBeenCalled();
  });
});

describe("no synthesizer present", () => {
  beforeEach(() => {
    (globalThis as any).window = {};   // no speechSynthesis at all
  });
  test("speechSupported is false and every call is a silent no-op", () => {
    expect(speechSupported()).toBe(false);
    const sp = createSpeaker("en-US");
    expect(() => { sp.feed("hi."); sp.end(); sp.cancel(); }).not.toThrow();
  });
});

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
  loadVoices,
  pickVoice,
  preferredVoiceLocale,
  speechSupported,
  utteranceLangFor,
  voiceLangFor,
} from "../lib/speech";

/** A minimal SpeechSynthesisVoice; only the fields the picker reads. */
function voice(lang: string, extra: Partial<SpeechSynthesisVoice> = {}): SpeechSynthesisVoice {
  return { lang, name: `v:${lang}`, default: false, localService: false, voiceURI: lang, ...extra } as SpeechSynthesisVoice;
}

/** A stubbed synthesizer. `voices` may start empty and be filled later via `arrive()`. */
function stubSynth(initial: SpeechSynthesisVoice[]) {
  const spoken: Array<{ text: string; lang: string; voice: SpeechSynthesisVoice | null }> = [];
  let voices = initial;
  const listeners: Array<() => void> = [];
  (globalThis as any).SpeechSynthesisUtterance = class {
    text: string; lang = ""; voice: SpeechSynthesisVoice | null = null;
    constructor(t: string) { this.text = t; }
  };
  const synth = {
    speak: (u: any): any => spoken.push({ text: u.text, lang: u.lang, voice: u.voice }),
    cancel: vi.fn(),
    getVoices: () => voices,
    addEventListener: (_: string, cb: () => void) => listeners.push(cb),
    removeEventListener: vi.fn(),
  };
  (globalThis as any).window = {
    speechSynthesis: synth,
    SpeechSynthesisUtterance: (globalThis as any).SpeechSynthesisUtterance,
  };
  return {
    spoken,
    synth,
    arrive(v: SpeechSynthesisVoice[]) { voices = v; listeners.splice(0).forEach((cb) => cb()); },
  };
}

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
  let spoken: ReturnType<typeof stubSynth>["spoken"];
  beforeEach(() => {
    ({ spoken } = stubSynth([voice("en-US")]));
  });
  const texts = () => spoken.map((s) => s.text);

  test("speaks each completed sentence as it streams", async () => {
    const sp = createSpeaker("en-US");
    await sp.feed("Hi there. ");
    await sp.feed("Reading now.");
    expect(texts()).toEqual(["Hi there.", "Reading now."]);
  });

  test("end() speaks the unterminated tail", async () => {
    const sp = createSpeaker("en-US");
    await sp.feed("a finished one. a dangling tail");
    expect(texts()).toEqual(["a finished one."]);
    await sp.end();
    expect(texts()).toEqual(["a finished one.", "a dangling tail"]);
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

// ---------------------------------------------------------------------------
// V1b: the voice follows the TEXT, not the interface. The bug this fixes: UI
// in English, Arslan replying in Chinese, an English voice reading Chinese.
// ---------------------------------------------------------------------------

describe("utteranceLangFor — the sentence's own script decides", () => {
  test("Chinese text under an English interface is spoken as Chinese", () => {
    expect(utteranceLangFor("打开桌面上的文件。", "en-US")).toBe("zh-CN");
  });

  test("kana marks Japanese even when kanji are present", () => {
    expect(utteranceLangFor("東京の天気です。", "en-US")).toBe("ja-JP");
  });

  test("Hangul is Korean", () => {
    expect(utteranceLangFor("안녕하세요.", "en-US")).toBe("ko-KR");
  });

  test("Cyrillic is Russian", () => {
    expect(utteranceLangFor("Привет, мир.", "en-US")).toBe("ru-RU");
  });

  test("Latin text cannot be told apart by script, so the hint wins", () => {
    // German and English look alike to a script check; trust what the user
    // said they speak rather than guess.
    expect(utteranceLangFor("Guten Morgen.", "de-DE")).toBe("de-DE");
  });

  test("Latin text under a non-Latin hint falls to English, not to the hint", () => {
    // The mirror of the original bug: a Chinese voice must not read English.
    expect(utteranceLangFor("Open Safari.", "zh-CN")).toBe("en-US");
  });

  test("text with no letters at all keeps the hint", () => {
    expect(utteranceLangFor("42.", "zh-CN")).toBe("zh-CN");
  });
});

describe("preferredVoiceLocale — what you SPEAK is what you want to HEAR", () => {
  test("the voice-input locale, when set, is the hint", () => {
    expect(preferredVoiceLocale("de-DE", "en")).toBe("de-DE");
  });
  test("empty or blank input locale falls back to the interface language", () => {
    expect(preferredVoiceLocale("", "zh")).toBe("zh-CN");
    expect(preferredVoiceLocale("   ", "ja")).toBe("ja-JP");
    expect(preferredVoiceLocale(undefined, undefined)).toBe("en-US");
  });
});

describe("pickVoice", () => {
  test("an exact tag beats a sibling of the same language", () => {
    const tw = voice("zh-TW"), cn = voice("zh-CN");
    expect(pickVoice([tw, cn], "zh-CN")).toBe(cn);
  });

  test("a sibling of the same language is used when there is no exact tag", () => {
    const tw = voice("zh-TW");
    expect(pickVoice([voice("en-US"), tw], "zh-CN")).toBe(tw);
  });

  test("among equals the engine's default wins, then an offline voice", () => {
    const a = voice("en-US"), b = voice("en-US", { default: true }), c = voice("en-US", { localService: true });
    expect(pickVoice([a, c, b], "en-US")).toBe(b);
    expect(pickVoice([a, c], "en-US")).toBe(c);
  });

  test("tags are matched without regard to case or underscore", () => {
    // Some WebKit builds report zh_CN; some engines lowercase. Same voice.
    const v = voice("zh_cn");
    expect(pickVoice([v], "zh-CN")).toBe(v);
  });

  test("no voice for that language at all is undefined, not a wrong-language voice", () => {
    expect(pickVoice([voice("en-US")], "ja-JP")).toBeUndefined();
  });
});

describe("loadVoices — the voice table loads asynchronously", () => {
  test("resolves at once when voices are already there", async () => {
    const { synth } = stubSynth([voice("en-US")]);
    expect(await loadVoices()).toEqual(synth.getVoices());
  });

  test("waits for voiceschanged when the table starts empty", async () => {
    const s = stubSynth([]);
    const p = loadVoices();
    s.arrive([voice("zh-CN")]);
    expect((await p).map((v) => v.lang)).toEqual(["zh-CN"]);
  });

  test("gives up after the bound and resolves empty rather than hanging", async () => {
    vi.useFakeTimers();
    try {
      stubSynth([]);
      const p = loadVoices(1500);
      vi.advanceTimersByTime(1500);
      expect(await p).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the speaker picks a voice per sentence", () => {
  test("a Chinese sentence under an English hint gets the Chinese voice", async () => {
    const zh = voice("zh-CN"), en = voice("en-US");
    const { spoken } = stubSynth([zh, en]);
    const sp = createSpeaker("en-US");
    await sp.feed("你好。Hello.");
    expect(spoken).toEqual([
      { text: "你好。", lang: "zh-CN", voice: zh },
      { text: "Hello.", lang: "en-US", voice: en },
    ]);
  });

  test("sentences fed before the voices arrive are spoken, in order, once they do", async () => {
    const s = stubSynth([]);
    const sp = createSpeaker("en-US");
    const a = sp.feed("First. ");
    const b = sp.feed("Second.");
    expect(s.spoken).toEqual([]);                 // nothing yet — no voices
    const zh = voice("zh-CN"), en = voice("en-US");
    s.arrive([zh, en]);
    await Promise.all([a, b]);
    expect(s.spoken.map((x) => [x.text, x.voice])).toEqual([["First.", en], ["Second.", en]]);
  });

  test("cancel() while waiting for voices drops what was queued", async () => {
    const s = stubSynth([]);
    const sp = createSpeaker("en-US");
    const p = sp.feed("Never said. ");
    sp.cancel();
    s.arrive([voice("en-US")]);
    await p;
    expect(s.spoken).toEqual([]);
    expect(s.synth.cancel).toHaveBeenCalled();
  });

  test("with no matching voice the utterance still carries the right lang", async () => {
    // The engine may still find something for the tag on its own; what we must
    // never do is hand it a voice of the wrong language.
    const { spoken } = stubSynth([voice("en-US")]);
    const sp = createSpeaker("en-US");
    await sp.feed("こんにちは。");
    expect(spoken).toEqual([{ text: "こんにちは。", lang: "ja-JP", voice: null }]);
  });
});

describe("the speaker says when it is speaking", () => {
  test("active from the first utterance until the last one ends", async () => {
    const { synth } = stubSynth([voice("en-US")]);
    const started: any[] = [];
    synth.speak = (u: any) => started.push(u);       // capture, do not auto-end
    const seen: boolean[] = [];
    const sp = createSpeaker("en-US", { onActive: (a) => seen.push(a) });
    await sp.feed("One. Two.");
    expect(seen).toEqual([true]);                     // once, not per sentence
    started[0].onend?.();
    expect(seen).toEqual([true]);                     // still one pending
    started[1].onend?.();
    expect(seen).toEqual([true, false]);
  });

  test("cancel() ends the active state even with utterances pending", async () => {
    const { synth } = stubSynth([voice("en-US")]);
    synth.speak = () => {};
    const seen: boolean[] = [];
    const sp = createSpeaker("en-US", { onActive: (a) => seen.push(a) });
    await sp.feed("Never finishes.");
    sp.cancel();
    expect(seen).toEqual([true, false]);
  });

  test("one utterance that both ends and errors settles once", async () => {
    // Engines have been seen to fire both on the same utterance. Counting it
    // twice drives `pending` negative, and a negative count never crosses back
    // to zero — so the speaker reports itself as speaking forever, and in
    // conversation mode the microphone it gates stays muted for the rest of
    // the session.
    const { synth } = stubSynth([voice("en-US")]);
    const started: any[] = [];
    synth.speak = (u: any) => started.push(u);
    const seen: boolean[] = [];
    const sp = createSpeaker("en-US", { onActive: (a) => seen.push(a) });
    await sp.feed("Twice.");
    started[0].onend?.();
    started[0].onerror?.();
    expect(seen).toEqual([true, false]);
    // The proof that the count is 0 and not -1: the next sentence must be
    // able to make it active again.
    await sp.feed("Again.");
    expect(seen).toEqual([true, false, true]);
  });

  test("an utterance error counts as ended", async () => {
    const { synth } = stubSynth([voice("en-US")]);
    const started: any[] = [];
    synth.speak = (u: any) => started.push(u);
    const seen: boolean[] = [];
    const sp = createSpeaker("en-US", { onActive: (a) => seen.push(a) });
    await sp.feed("Oops.");
    started[0].onerror?.();
    expect(seen).toEqual([true, false]);
  });
});

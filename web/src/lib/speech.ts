/**
 * Speaking the assistant's reply out loud (voice output, V1 / V1b).
 *
 * Frontend Web Speech (`window.speechSynthesis`), not a native bridge: the
 * webview already has it (probed on a real packaged build), it needs no
 * entitlement, and it degrades to silence when absent. Every call is
 * capability-guarded so an environment without the API simply stays quiet
 * rather than throwing.
 *
 * The reply arrives as a stream of chunks. We speak it sentence by sentence so
 * the voice starts almost immediately and tracks the text, rather than waiting
 * for the whole answer. The segmenter below is the pure, testable core; the
 * synthesis wrapper is the thin unsafe edge.
 *
 * V1b — the voice follows the TEXT, not the interface. V1 set every
 * utterance's lang from the UI language and never chose a voice, so an
 * English interface had an English voice reading Chinese replies (the user's
 * words: the sound had nothing to do with the output). Two things fix that:
 * a per-sentence script check picks the language, and a voice of that
 * language is chosen from the engine's table — after waiting for the table,
 * which loads asynchronously (`getVoices()` returned 0 in the probe).
 */

/** Sentence terminators worth breaking on — Latin and CJK, plus a newline.
 *  The CJK stops are written as escapes, not literals, so this file stays free
 *  of hardcoded CJK (the no-hardcoded-cjk guard) while matching identically:
 *  \u3002 。 (ideographic full stop), \uFF01 ！, \uFF1F ？. */
const _BOUNDARY = /[.!?\n\u3002\uFF01\uFF1F]/;

/**
 * Feed streamed text in, get back completed sentences to speak.
 *
 * Holds an incomplete tail until a terminator arrives, so a chunk that splits
 * mid-word ("hel" + "lo.") does not speak twice. `flush()` returns whatever is
 * left when the stream ends (an answer need not end in punctuation).
 */
export function createSentenceFeeder() {
  let buf = "";
  return {
    /** Push a chunk; returns any sentences it completed (may be empty). */
    push(chunk: string): string[] {
      buf += chunk;
      const out: string[] = [];
      let m: RegExpMatchArray | null;
      // Emit each completed sentence including its terminator.
      while ((m = buf.match(_BOUNDARY)) && m.index !== undefined) {
        const end = m.index + 1;
        // Progress guard: end is always >= 1 here, so the slice below always
        // shrinks buf. Kept explicit because a zero-advance loop on this (the
        // UI) thread would hang the whole app — a boundary-math bug must fail
        // loudly, not spin. (A mutation to `m.index` proved the hazard real.)
        if (end <= 0) break;
        const sentence = buf.slice(0, end).trim();
        buf = buf.slice(end);
        if (sentence) out.push(sentence);
      }
      return out;
    },
    /** The trailing partial sentence, if any, cleared. */
    flush(): string[] {
      const rest = buf.trim();
      buf = "";
      return rest ? [rest] : [];
    },
  };
}

/** Whether this environment can speak at all. */
export function speechSupported(): boolean {
  return typeof window !== "undefined"
    && typeof window.speechSynthesis !== "undefined"
    && typeof window.SpeechSynthesisUtterance !== "undefined";
}

/**
 * The one place a UI language code becomes a BCP-47 tag a speech engine wants.
 *
 * Exported as a table rather than hidden in a switch because the settings
 * picker needs the same mapping: two copies would drift, and a drifted voice
 * locale is exactly the bug that made an English voice read Chinese.
 */
export const VOICE_LOCALE_BY_CODE: Record<string, string> = {
  zh: "zh-CN",
  "zh-cn": "zh-CN",
  ja: "ja-JP",
  de: "de-DE",
  fr: "fr-FR",
  es: "es-ES",
  en: "en-US",
};

/** Map the app's language setting to a BCP-47 tag. Unknown codes read as en-US. */
export function voiceLangFor(appLanguage: string | undefined): string {
  return VOICE_LOCALE_BY_CODE[(appLanguage || "").toLowerCase()] ?? "en-US";
}

/**
 * The language a listener most likely wants to HEAR: the one they said they
 * SPEAK, else the interface language. Shared by the speaker's hint and the
 * recogniser so the two cannot drift apart.
 */
export function preferredVoiceLocale(
  voiceInputLocale: string | undefined,
  appLanguage: string | undefined,
): string {
  return (voiceInputLocale || "").trim() || voiceLangFor(appLanguage);
}

// Script ranges, written as escapes (the no-hardcoded-cjk guard). A script
// check is deliberately the whole of the detector: it is exact for the scripts
// it knows and honest about the ones it cannot tell apart (Latin languages),
// where it defers to what the user told us instead of guessing.
const _KANA = /[\u3040-\u30ff]/;          // hiragana + katakana → Japanese
const _HAN = /[\u3400-\u4dbf\u4e00-\u9fff]/; // CJK ideographs → Chinese (unless kana)
const _HANGUL = /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/;
const _CYRILLIC = /[\u0400-\u04ff]/;
const _LATIN = /[A-Za-z\u00c0-\u024f]/;
/** Primary subtags whose voices must not be handed Latin text. */
const _NON_LATIN_PRIMARY = new Set(["zh", "ja", "ko", "ru"]);

/**
 * The BCP-47 tag one sentence should be spoken in.
 *
 * Script decides where it can (CJK, Hangul, Cyrillic). Latin text keeps the
 * hint — German and English look the same to a script check, and the hint is
 * what the user said they speak — unless the hint is itself a non-Latin
 * language, in which case English: a Chinese voice reading English is the
 * mirror of the bug this exists to fix. Text with no letters at all (a bare
 * number) keeps the hint.
 */
export function utteranceLangFor(text: string, hint: string): string {
  if (_KANA.test(text)) return "ja-JP";
  if (_HAN.test(text)) return "zh-CN";
  if (_HANGUL.test(text)) return "ko-KR";
  if (_CYRILLIC.test(text)) return "ru-RU";
  if (_LATIN.test(text) && _NON_LATIN_PRIMARY.has(_primary(hint))) return "en-US";
  return hint;
}

function _norm(tag: string): string {
  return tag.replace(/_/g, "-").toLowerCase();
}
function _primary(tag: string): string {
  return _norm(tag).split("-")[0];
}

/**
 * The best voice in `voices` for `lang`: an exact tag first, else any voice
 * of the same language (zh-TW for zh-CN beats silence). Within a tier the
 * engine's default wins, then an offline voice. `undefined` when the engine
 * has nothing for that language — never a voice of the wrong one.
 */
export function pickVoice(
  voices: readonly SpeechSynthesisVoice[],
  lang: string,
): SpeechSynthesisVoice | undefined {
  const want = _norm(lang);
  const primary = _primary(lang);
  const rank = (v: SpeechSynthesisVoice) => (v.default ? 0 : v.localService ? 1 : 2);
  const best = (pool: SpeechSynthesisVoice[]) =>
    pool.length ? pool.reduce((a, b) => (rank(b) < rank(a) ? b : a)) : undefined;
  return best(voices.filter((v) => _norm(v.lang) === want))
    ?? best(voices.filter((v) => _primary(v.lang) === primary));
}

/**
 * The engine's voice table, once it exists. Engines populate it asynchronously
 * and signal `voiceschanged`; asking too early returns `[]`. Bounded: if the
 * event never comes (some engines fire it only once, before we listened, and
 * still report nothing) we resolve empty rather than muting the reply forever.
 */
export function loadVoices(timeoutMs = 1500): Promise<SpeechSynthesisVoice[]> {
  if (!speechSupported()) return Promise.resolve([]);
  const synth = window.speechSynthesis;
  const now = synth.getVoices?.() ?? [];
  if (now.length) return Promise.resolve(now);
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      synth.removeEventListener?.("voiceschanged", finish);
      resolve(synth.getVoices?.() ?? []);
    };
    const timer = setTimeout(finish, timeoutMs);
    synth.addEventListener?.("voiceschanged", finish);
  });
}

/**
 * A speaker with one language HINT. `feed()` takes streamed chunks and speaks
 * the sentences they complete, each in the language its own text calls for;
 * `end()` flushes the tail; `cancel()` stops at once and drops anything still
 * waiting for the voice table. All no-ops when unsupported.
 *
 * feed()/end() resolve once their sentences have been handed to the engine;
 * callers that stream may ignore the promise, tests await it.
 */
export function createSpeaker(hint: string) {
  const feeder = createSentenceFeeder();
  const enabled = speechSupported();
  // One load per speaker (= per reply). Every say() chains on the same
  // promise, so sentences reach the engine in the order they were fed.
  const ready = enabled ? loadVoices() : Promise.resolve([]);
  let cancelled = false;

  function say(sentence: string): Promise<void> {
    if (!sentence) return Promise.resolve();
    return ready.then((voices) => {
      if (cancelled) return;
      const u = new SpeechSynthesisUtterance(sentence);
      u.lang = utteranceLangFor(sentence, hint);
      const v = pickVoice(voices, u.lang);
      if (v) u.voice = v;
      window.speechSynthesis.speak(u);
    });
  }

  return {
    async feed(chunk: string) {
      if (!enabled) return;
      for (const s of feeder.push(chunk)) await say(s);
    },
    async end() {
      if (!enabled) return;
      for (const s of feeder.flush()) await say(s);
    },
    cancel() {
      cancelled = true;
      if (enabled) window.speechSynthesis.cancel();
    },
  };
}

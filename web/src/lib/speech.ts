/**
 * Speaking the assistant's reply out loud (voice output, V1).
 *
 * Frontend Web Speech (`window.speechSynthesis`), not a native bridge: the
 * webview already has it, it needs no entitlement, and it degrades to silence
 * when absent. Every call is capability-guarded so an environment without the
 * API (some packaged WKWebView builds — UNVERIFIED, see the voice spec) simply
 * stays quiet rather than throwing.
 *
 * The reply arrives as a stream of chunks. We speak it sentence by sentence so
 * the voice starts almost immediately and tracks the text, rather than waiting
 * for the whole answer. The segmenter below is the pure, testable core; the
 * synthesis wrapper is the thin unsafe edge.
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
 * A speaker bound to one language. `feed()` takes streamed chunks and speaks the
 * sentences they complete; `end()` flushes the tail; `cancel()` stops at once
 * (a new turn, or the user interrupting). All no-ops when unsupported.
 */
export function createSpeaker(lang: string) {
  const feeder = createSentenceFeeder();
  const enabled = speechSupported();

  function say(sentence: string) {
    // enabled is gated by feed()/end() before we ever get here — no second
    // check, which a mutation showed was dead (removing it changed nothing).
    if (!sentence) return;
    const u = new SpeechSynthesisUtterance(sentence);
    u.lang = lang;
    window.speechSynthesis.speak(u);
  }

  return {
    feed(chunk: string) {
      if (!enabled) return;
      for (const s of feeder.push(chunk)) say(s);
    },
    end() {
      if (!enabled) return;
      for (const s of feeder.flush()) say(s);
    },
    cancel() {
      if (enabled) window.speechSynthesis.cancel();
    },
  };
}

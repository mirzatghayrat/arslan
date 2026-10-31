/**
 * Text from outside (a SKILL.md, a server's label, a registry entry) as the web shows it (v0.1.64 UNI1,
 * docs/plans/0164/CAPX-followups.md). Names come cleaned from the server (`untrusted.clean_name`); these are
 * the web's side of the same rule, for every place that shows such text:
 * - `isolate`: a name inside one of Arslan's own sentences, so bidi controls in it cannot reorder the sentence.
 * - `Escaped`: text as stored, with each bidi override and isolate control shown as a visible marker. A skill's
 *   text keeps them (UNI1: flagged, not stripped), and the card must still show exactly what is stored (#472 F4).
 */

/** Marks and controls that could close an isolate early or reorder what follows it (#500 recheck). */
const BIDI_CONTROLS = /[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;
/** The controls that reorder text: embeddings, overrides and isolates with their pops. Shown, never applied. */
const REORDERING = /[\u202A-\u202E\u2066-\u2069]/;

/** A name from outside inside one of Arslan's sentences: isolated, so bidi controls in it cannot reorder the
 *  sentence around it (#500 review). */
export const isolate = (text: string) => `\u2068${text.replace(BIDI_CONTROLS, "")}\u2069`;

const hex = (ch: string) => `U+${ch.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`;

/** `text` as stored, with every reordering control shown as a marker (`U+202E`) instead of applied. Inline it is
 *  isolated (`<bdi>`) from the words around it; `block` (a whole box of its own, like a skill's text) is not. */
export function Escaped({ text, block = false }: { text: string | null | undefined; block?: boolean }) {
  const parts = [...(text ?? "")].reduce<string[]>((out, ch) => {
    if (REORDERING.test(ch)) out.push(ch, "");
    else out[out.length - 1] += ch;
    return out;
  }, [""]);
  const shown = parts.map((part, i) => REORDERING.test(part) && part.length === 1
    ? <span key={i} data-testid="escaped-control" title={hex(part)}
        className="mx-px rounded bg-fill px-1 font-mono text-[10px] text-muted-foreground">{hex(part)}</span>
    : part);
  return block ? <>{shown}</> : <bdi>{shown}</bdi>;
}

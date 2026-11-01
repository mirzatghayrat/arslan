import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { PRESENTATION_BASES } from "./emojiBases";

/**
 * Text from outside (a SKILL.md, a server's label, a registry entry) as the web shows it (v0.1.64 UNI1,
 * docs/plans/0164/CAPX-followups.md). Names come cleaned from the server (`untrusted.clean_name`); these are
 * the web's side of the same rule, for every place that shows such text:
 * - `isolate`: a name inside one of Arslan's own sentences, so bidi controls in it cannot reorder the sentence.
 * - `Escaped`: text as stored, with each bidi override and isolate control shown as a visible marker. A skill's
 *   text keeps them (UNI1: flagged, not stripped), and the card must still show exactly what is stored (#472 F4).
 *   UNI1b (the user's option B): each run of characters that show nothing is a marker too, always.
 */

/** Marks and controls that could close an isolate early or reorder what follows it (#500 recheck). */
const BIDI_CONTROLS = /[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;
/** The controls that reorder text: embeddings, overrides and isolates with their pops. Shown, never applied. */
const REORDERING = /[\u202A-\u202E\u2066-\u2069]/;

/** A name from outside inside one of Arslan's sentences: isolated, so bidi controls in it cannot reorder the
 *  sentence around it (#500 review). */
export const isolate = (text: string) => `\u2068${text.replace(BIDI_CONTROLS, "")}\u2069`;

const hex = (ch: string) => `U+${ch.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}`;
const hexOf = (cp: number) => `U+${cp.toString(16).toUpperCase().padStart(4, "0")}`;

/** UNI1b: what a skill's text may hold that shows nothing at all, as the server's `untrusted.hidden_runs` has it:
 *  Unicode's default-ignorable code points and the blank braille pattern, but ZWNJ, ZWJ, LRM, RLM and ALM (ordinary
 *  text needs them) and the bidi controls (shown with their own marker above). Every table is explicit code point
 *  ranges, never the Unicode database, so both sides agree whatever Unicode version each ships (#586 review F5);
 *  spec/unicode/hidden-characters.json holds the same tables and the cases both pass. */
export const HIDDEN: [number, number][] = [
  [0x00ad, 0x00ad], [0x034f, 0x034f], [0x115f, 0x1160], [0x17b4, 0x17b5], [0x180b, 0x180f], [0x200b, 0x200b],
  [0x2060, 0x2065], [0x206a, 0x206f], [0x2800, 0x2800], [0x3164, 0x3164], [0xfe00, 0xfe0f], [0xfeff, 0xfeff],
  [0xffa0, 0xffa0], [0xfff0, 0xfff8], [0x1bca0, 0x1bca3], [0x1d173, 0x1d17a], [0xe0000, 0xe0fff]];
/** Runs of these show as one marker with their range: variation selectors, their supplement, and tags. */
export const RUN_RANGES: [string, number, number][] = [
  ["U+FE00\u2013FE0F", 0xfe00, 0xfe0f], ["U+E0100\u2013E01EF", 0xe0100, 0xe01ef], ["U+E0000\u2013E007F", 0xe0000, 0xe007f]];
/** #586 review F1, re-check R1 and R2: one selector goes uncounted only when it does what ordinary text uses one
 *  for: VS15 or VS16 after an emoji or a keycap's base (PRESENTATION_BASES), or an ideographic variation selector
 *  after a CJK ideograph, at most IVS_UNCOUNTED_MAX of those in a text. Every other selector is counted. */
export const PRESENTATION_SELECTORS = [0xfe0e, 0xfe0f];
export const IDEOGRAPHS: [number, number][] = [[0x3400, 0x4dbf], [0x4e00, 0x9fff], [0xf900, 0xfaff], [0x20000, 0x323af]];
export const IVS_UNCOUNTED_MAX = 8;
/** The tags of the three RGI subdivision flags (England, Scotland, Wales), after U+1F3F4 and before U+E007F. */
export const FLAG_TAGS = ["gbeng", "gbsct", "gbwls"];

const within = (cp: number, ranges: [number, number][]) => ranges.some(([lo, hi]) => lo <= cp && cp <= hi);
const runRange = (cp: number) => RUN_RANGES.find(([, lo, hi]) => lo <= cp && cp <= hi)?.[0] ?? null;
const isSelector = (cp: number) => (cp >= 0xfe00 && cp <= 0xfe0f) || (cp >= 0xe0100 && cp <= 0xe01ef);

function takesSelector(prev: number | undefined, selector: number): boolean {
  if (prev === undefined) return false;
  if (PRESENTATION_SELECTORS.includes(selector)) return within(prev, PRESENTATION_BASES);
  return selector >= 0xe0100 && selector <= 0xe01ef && within(prev, IDEOGRAPHS);
}

/** One run of characters that show nothing: where it starts (in code points) and what it holds. */
export type HiddenRun = { start: number; cps: number[] };

/** UNI1b: each run of characters that show nothing, in order. A run is one code point repeated, or characters of
 *  one range. Not counted: one selector that does what ordinary text uses one for, and an RGI flag's tags. */
export function hiddenRuns(text: string | null | undefined): HiddenRun[] {
  const cps = [...(text ?? "")].map(ch => ch.codePointAt(0)!);
  const flagged = new Set<number>();
  cps.forEach((cp, i) => {
    const tags = cps.slice(i + 1, i + 6);
    // #586 review F7: tag letters only (U+E0061-E007A); ASCII letters spelling a flag are not one.
    if (cp === 0x1f3f4 && tags.length === 5 && tags.every(t => t >= 0xe0061 && t <= 0xe007a)
        && FLAG_TAGS.includes(String.fromCharCode(...tags.map(t => t - 0xe0000))) && cps[i + 6] === 0xe007f) {
      for (let j = i + 1; j <= i + 6; j++) flagged.add(j);
    }
  });
  const runs: HiddenRun[] = [];
  let open = false, ivsUncounted = 0;
  cps.forEach((cp, i) => {
    let hidden = !flagged.has(i) && within(cp, HIDDEN);
    if (hidden && isSelector(cp) && !(i + 1 < cps.length && isSelector(cps[i + 1]))
        && takesSelector(i ? cps[i - 1] : undefined, cp)) {
      const ivs = cp >= 0xe0100 && cp <= 0xe01ef;
      if (!ivs || ivsUncounted < IVS_UNCOUNTED_MAX) {        // re-check R1: past the cap, each one counts
        hidden = false;
        if (ivs) ivsUncounted += 1;
      }
    }
    if (hidden) {
      const last = open ? runs[runs.length - 1]?.cps : undefined;
      const lastCp = last?.[last.length - 1];
      if (last && lastCp !== undefined && (lastCp === cp || (runRange(cp) !== null && runRange(cp) === runRange(lastCp)))) {
        last.push(cp);
      } else {
        runs.push({ start: i, cps: [cp] });
      }
    }
    open = hidden;
  });
  return runs;
}

/** A run as its marker shows it: `U+200B`, `16 × U+2800`, `14 × U+E0100–E01EF`. */
export function hiddenLabel(cps: number[]): string {
  const one = hexOf(cps[0]);
  if (cps.length === 1) return one;
  return `${cps.length} \u00d7 ${new Set(cps).size === 1 ? one : runRange(cps[0])}`;
}

/** How many characters of `text` show nothing (the save card's notice). */
export const hiddenCount = (text: string | null | undefined) =>
  hiddenRuns(text).reduce((n, run) => n + run.cps.length, 0);

/** `text` as stored, with every reordering control shown as a marker (`U+202E`) instead of applied. Inline it is
 *  isolated (`<bdi>`) from the words around it; `block` (a whole box of its own, like a skill's text) is not. */
export function Escaped({ text, block = false }: { text: string | null | undefined; block?: boolean }) {
  const { t } = useTranslation();
  const chars = [...(text ?? "")];
  // UNI1b: each run of characters that show nothing becomes one marker in their place.
  const runAt = new Map(hiddenRuns(text).map(run => [run.start, run]));
  const shown: ReactNode[] = [];
  let plain = "";
  const marker = (node: ReactNode) => { shown.push(plain, node); plain = ""; };
  for (let i = 0; i < chars.length; i++) {
    const run = runAt.get(i);
    if (run) {
      const label = hiddenLabel(run.cps);
      marker(<span key={`h${i}`} data-testid="hidden-marker" title={label} role="img"
        aria-label={t("discover.hidden_marker", { label })}
        className="mx-px rounded bg-ask-soft px-1 font-mono text-[10px] text-ask">{label}</span>);
      i += run.cps.length - 1;
    } else if (REORDERING.test(chars[i])) {
      marker(<span key={`c${i}`} data-testid="escaped-control" title={hex(chars[i])}
        className="mx-px rounded bg-fill px-1 font-mono text-[10px] text-muted-foreground">{hex(chars[i])}</span>);
    } else {
      plain += chars[i];
    }
  }
  shown.push(plain);
  return block ? <>{shown}</> : <bdi>{shown}</bdi>;
}

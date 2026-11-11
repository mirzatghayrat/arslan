/**
 * A hook's command line as its box shows it (HOOK-4, #853 review): every character the shell will read is shown, and
 * nothing that would move or hide text is applied.
 * - A line break (LF) is a `⏎` marker, then the real break: the box keeps `white-space: pre-wrap`, so a second line
 *   reads as a second command, as the shell runs it.
 * - Every other control character is an escape, `\x1B` style (four hex digits past U+00FF): tab, CR, ESC and the rest
 *   of C0, DEL, C1, the line and paragraph separators (U+2028, U+2029, which would break the line where the shell
 *   sees none), the bidi embeddings, overrides and isolates (U+202A to U+202E, U+2066 to U+2069), and (#853 r2) the
 *   direction marks LRM, RLM and ALM (U+200E, U+200F, U+061C) and the joiners ZWNJ and ZWJ (U+200C, U+200D), which
 *   `Escaped` leaves unmarked beside right-to-left or joining letters, as prose uses them.
 * The other characters that show nothing (U+200B, U+2060 to U+2064, U+FEFF and the rest of UNI1b's table) always get
 * `Escaped`'s markers. The box itself is laid out left to right (`CommandText`), so no letter can reorder it.
 * The ranges are code point numbers, not escapes in a pattern, so no tool can turn them into the characters.
 */
export type CommandPart = { kind: "text"; text: string } | { kind: "break" } | { kind: "escape"; text: string };

const LF = 0x0a;
export const CONTROLS: [number, number][] = [
  [0x00, 0x09], [0x0b, 0x1f], [0x7f, 0x9f], [0x061c, 0x061c], [0x200c, 0x200f], [0x2028, 0x2029], [0x202a, 0x202e],
  [0x2066, 0x2069]];

const isControl = (cp: number) => CONTROLS.some(([lo, hi]) => lo <= cp && cp <= hi);
const hexOf = (cp: number, width: number) => cp.toString(16).toUpperCase().padStart(width, "0");

/** `\x1B` for a code point up to U+00FF; past it, a backslash, `u` and four hex digits (U+202E's). */
export function escapeOf(cp: number): string {
  return cp <= 0xff ? `\\x${hexOf(cp, 2)}` : `\\u${hexOf(cp, 4)}`;
}

/** `text` split into what the box shows: plain text, line breaks and escapes, in order. */
export function commandParts(text: string): CommandPart[] {
  const parts: CommandPart[] = [];
  let plain = "";
  const flush = () => { if (plain) parts.push({ kind: "text", text: plain }); plain = ""; };
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    if (cp === LF) { flush(); parts.push({ kind: "break" }); }
    else if (isControl(cp)) { flush(); parts.push({ kind: "escape", text: escapeOf(cp) }); }
    else plain += ch;
  }
  flush();
  return parts;
}

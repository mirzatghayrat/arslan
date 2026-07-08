/** [[wikilink]] autocomplete helpers for the note editor. Mirrors `lib/mentions.ts` —
 *  pure + framework-free so they can be unit-tested without a DOM. */

export interface WikilinkToken {
  /** Index of the first `[` of the opening `[[` in the value. */
  at: number;
  /** Text typed after the `[[`, up to the caret (may be empty right after typing `[[`). */
  query: string;
}

/**
 * The active `[[` token immediately before the caret, or null. The token runs from the
 * `[[` to the caret with no `]` or newline in between — once `]]` closes it, it's inert.
 */
export function activeWikilink(value: string, caret: number): WikilinkToken | null {
  const c = Math.max(0, Math.min(caret, value.length));
  const upto = value.slice(0, c);
  const m = /\[\[([^\]\n]*)$/.exec(upto);
  if (!m) return null;
  return { at: c - m[1].length - 2, query: m[1] };
}

/**
 * Replace the active [[token (`token.at`..`caret`) with `[[name]] ` and return the new
 * value plus the caret position just after the inserted link.
 */
export function insertWikilink(
  value: string,
  token: WikilinkToken,
  caret: number,
  name: string,
): { value: string; caret: number } {
  const before = value.slice(0, token.at);
  const after = value.slice(Math.max(token.at, caret));
  const insert = `[[${name}]] `;
  return { value: `${before}${insert}${after}`, caret: (before + insert).length };
}

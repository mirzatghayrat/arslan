/** @-mention autocomplete helpers for the composer. Pure + framework-free so they can be
 *  unit-tested without a DOM. */

export interface MentionToken {
  /** Index of the `@` in the value. */
  at: number;
  /** Text typed after the `@`, up to the caret (may be empty right after typing `@`). */
  query: string;
}

/**
 * The active @-mention token immediately before the caret, or null. The `@` must sit at the
 * start of the input or right after whitespace (so an email like `a@b` never triggers), and
 * the token runs from the `@` to the caret with no spaces or further `@` in between.
 */
export function activeMention(value: string, caret: number): MentionToken | null {
  const c = Math.max(0, Math.min(caret, value.length));
  const upto = value.slice(0, c);
  const m = /(?:^|\s)@([^\s@]*)$/.exec(upto);
  if (!m) return null;
  return { at: c - m[1].length - 1, query: m[1] };
}

/**
 * Rank items for a query: name STARTS-WITH the query first, then merely CONTAINS it, both
 * case-insensitive. An empty query returns all named items in their original order. Items
 * without a usable name are dropped.
 */
export function filterRoster<T extends { spawnName: string | null }>(members: T[], query: string): T[] {
  const named = members.filter((m) => (m.spawnName ?? "").trim());
  const q = query.trim().toLowerCase();
  if (!q) return named;
  const starts: T[] = [];
  const contains: T[] = [];
  for (const m of named) {
    const n = (m.spawnName ?? "").toLowerCase();
    if (n.startsWith(q)) starts.push(m);
    else if (n.includes(q)) contains.push(m);
  }
  return [...starts, ...contains];
}

/**
 * Replace the active @token (`token.at`..`caret`) with `@name ` and return the new value plus
 * the caret position just after the inserted mention.
 */
export function insertMention(
  value: string,
  token: MentionToken,
  caret: number,
  name: string,
): { value: string; caret: number } {
  const before = value.slice(0, token.at);
  const after = value.slice(Math.max(token.at, caret));
  const insert = `@${name} `;
  return { value: `${before}${insert}${after}`, caret: (before + insert).length };
}

/**
 * FMT1 (0.1.64): a reply still streaming, cut into top-level Markdown blocks, so a finished block is parsed once and the cost of
 * a token doesn't grow with the reply. Streamdown does the same with marked's lexer; this needs only to find a safe place to
 * cut, with no new dependency, and a cut it misses only costs a bigger block.
 *
 * A block ends at a blank line, if the next line can't belong to it: not inside a fence, not indented (more of a list item, or
 * indented code), not a list marker (the next item of a loose list). What a cut can't show while streaming, such as a reference
 * link whose definition is in another block, shows when the finished reply is parsed whole.
 */
const FENCE_OPEN = /^ {0,3}(`{3,}(?=[^`]*$)|~{3,})/;
const FENCE_CLOSE = /^ {0,3}(`{3,}|~{3,})\s*$/;
const INDENTED_OR_LIST_ITEM = /^(\s|[-*+](\s|$)|\d{1,9}[.)](\s|$))/;

export function splitBlocks(text: string): string[] {
  const blocks: string[] = [];
  let start = 0;
  let fence = '';
  let afterBlank = false;
  for (let at = 0, next = 0; at < text.length; at = next) {
    const newline = text.indexOf('\n', at);
    next = newline < 0 ? text.length : newline + 1;
    const line = text.slice(at, next);
    if (fence) {
      const close = FENCE_CLOSE.exec(line)?.[1];
      if (close && close[0] === fence[0] && close.length >= fence.length) fence = '';
      continue;
    }
    if (afterBlank && !INDENTED_OR_LIST_ITEM.test(line)) {
      blocks.push(text.slice(start, at));
      start = at;
    }
    afterBlank = !line.trim();
    fence = FENCE_OPEN.exec(line)?.[1] ?? '';
  }
  if (start < text.length) blocks.push(text.slice(start));
  return blocks;
}

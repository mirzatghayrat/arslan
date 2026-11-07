/**
 * Whether a reply is too costly to hand to the Markdown parser. A reply is text outside content can steer, the parser runs on the
 * main thread and can't be stopped, and it is quadratic in the delimiters of one run of inline text: in real WebKit 16 kB of `*a`
 * takes 2 s and 64 kB takes 72 s, and a stored reply freezes the window again each time it's opened. Nesting past a few thousand
 * levels throws. The size of a reply says little: 256 kB of ordinary prose takes 0.5 s.
 *
 * So this estimates the parser's cost in one pass over the lines, and calls no parser (even with inline parsing off, it takes 10 s
 * on these replies). cmark and markdown-it stay fast with limits inside the parser, markdown-it's nesting limit is this 100, and
 * we can't change micromark, so the limit stands in front of it. Over the limit, a reply is shown as written.
 *
 * Code isn't read inline, so a fence doesn't count, but only one the parser is sure to agree is a fence. Every doubt counts the
 * text, which costs a reply its formatting and never freezes the window. markdown-parse-limit.test.tsx holds this against the parser.
 */

/** At the limit the worst shape (nested emphasis) takes about 1 s in WebKit's engine on a heavily loaded machine; most take far less. */
export const COST_LIMIT = 4000 ** 2;
const MAX_NESTING = 100;

/** Brackets cost several times what emphasis does (nested images at 2,000 take 2 s), so a table can keep 300 rows of bold and links. */
const BRACKET_WEIGHT = 4;
const LINE_END = /\r\n?/g;
const STAR = 42, PLUS = 43, DASH = 45, DOT = 46, ZERO = 48, NINE = 57, LESS = 60, GREATER = 62, BRACKET = 91, BACKSLASH = 92;
const CLOSE_BRACKET = 93, UNDERSCORE = 95, BACKTICK = 96, PIPE = 124, TILDE = 126, DOLLAR = 36, TAB = 9, SPACE = 32, PAREN = 41;
const BYTE_ORDER_MARK = 0xFEFF;

/** After this offset's list marker or quote mark, or -1 if there's none. */
function afterContainer(line: string, at: number): number {
  const c = line.charCodeAt(at);
  if (c === GREATER) return at + 1;
  let end = at;
  if (c === DASH || c === PLUS || c === STAR) end = at + 1;
  else {
    while (end - at < 9 && line.charCodeAt(end) >= ZERO && line.charCodeAt(end) <= NINE) end++;
    if (end === at || (line.charCodeAt(end) !== DOT && line.charCodeAt(end) !== PAREN)) return -1;
    end++;
  }
  const next = line.charCodeAt(end);
  return next === SPACE || next === TAB ? end + 1 : -1;
}

/** The fence that a line would open at this offset. */
function fenceAt(line: string, at: number): string {
  const c = line.charCodeAt(at);
  if (c !== BACKTICK && c !== TILDE) return '';
  let end = at + 1;
  while (line.charCodeAt(end) === c) end++;
  if (end - at < 3 || (c === BACKTICK && line.includes('`', end))) return '';
  return line.slice(at, end);
}

function closesFence(line: string, fence: string): boolean {
  let start = 0;
  while (start < 3 && line.charCodeAt(start) === SPACE) start++;
  let end = line.length;   // only a space or a tab may follow: to the parser, any other white space is text
  while (end > start && (line.charCodeAt(end - 1) === SPACE || line.charCodeAt(end - 1) === TAB)) end--;
  if (end - start < fence.length) return false;
  for (let i = start; i < end; i++) if (line[i] !== fence[0]) return false;
  return true;
}

/** An HTML block, a math block (or a TeX one the pre-pass makes math) or a definition's title can hold a line that looks like a fence. */
function canHideFence(line: string, at: number): boolean {
  const c = line.charCodeAt(at);
  if (c === LESS) return true;
  if (c === DOLLAR) return line.charCodeAt(at + 1) === DOLLAR;
  if (c === BACKSLASH) return line.charCodeAt(at + 1) === BRACKET;
  return c === BRACKET && line.slice(at, at + 1024).includes(']:');   // a label is at most 999 characters
}

/** What the parser would spend on this text, as the sum of each run's delimiters squared: Infinity when it nests too deep. */
export function markdownCost(text: string): number {
  let cost = 0;
  let run = 0;
  let fence = '';
  let believeFences = true;
  // The parser drops a byte order mark, so it mustn't hide a fence on the first line.
  const body = text.charCodeAt(0) === BYTE_ORDER_MARK ? text.slice(1) : text;
  for (const line of body.replace(LINE_END, '\n').split('\n')) {
    if (fence) {
      if (closesFence(line, fence)) fence = '';
      continue;
    }
    let at = 0;
    let depth = 0;
    for (; at < line.length; at++) {
      const c = line.charCodeAt(at);
      if (c === SPACE || c === TAB) continue;
      const after = afterContainer(line, at);
      if (after < 0) break;
      if (++depth > MAX_NESTING) return Infinity;
      at = after - 1;
    }
    if (at >= line.length && depth === 0) {   // blank. A line of only container marks may not end a run, so it isn't counted as ending one
      cost += run * run;
      run = 0;
      continue;
    }
    const opened = fenceAt(line, at);
    if (opened && believeFences && at === 0) {
      fence = opened;
      cost += run * run;
      run = 0;
      continue;
    }
    // Only a fence at the left margin is followed: elsewhere it may or may not open one, and the next ``` may then close it.
    if (opened || canHideFence(line, at)) believeFences = false;
    let pipes = 0;
    for (let i = 0; i < line.length; i++) {
      const c = line.charCodeAt(i);
      if (c === PIPE) pipes++;
      else if (c === STAR || c === UNDERSCORE || c === TILDE) run++;
      else if (c === BRACKET || c === CLOSE_BRACKET) run += BRACKET_WEIGHT;
    }
    cost += pipes * pipes;
  }
  return cost + run * run;
}

export function tooCostlyToParse(text: string): boolean {
  return markdownCost(text) > COST_LIMIT;
}

/**
 * FMT1 PR 2 (0.1.64): a pass ahead of the parser, for what remark-math can't read as a model meant it.
 * - \[...\] and \(...\): Markdown would eat the backslashes, so they become $$.
 * - A line that starts with $$ and has text after it: remark-math keeps that text as a fence's meta, which nothing shows, and
 *   the fence runs on over whatever follows. It becomes a block if a later line closes it, and escaped text if none does.
 * - $$x$$ alone on a line becomes a block, so that it's display, as \[x\] is.
 * \[...\] is display only when it fills its lines, with no blank line inside, and it keeps those lines' containers, so it stays
 * in its list or quote. Anywhere else, \[ is what Markdown means by it: an escaped bracket.
 *
 * What Markdown reads literally (code, a link's target, a definition, HTML, a bare URL) and whether a list marker is really one
 * depend on the blocks around them, so the parser says: it reads the reply first, with no $$ to swallow anything, and what it calls
 * literal is blanked out before anything here looks. A formula must open and close outside the blanks, and may hold some in a line:
 * it opened first, as math does in the real parse, and TeX can look like a link. That's a second parse, so only a reply with
 * something to rewrite pays it: 2 x 13 ms for 17 kB of formulas, measured in WKWebView.
 *
 * No lookbehind: the app runs on WebKit 14 (macOS 11). Every span below stops at the next opener, so openers cost linear time.
 */
import type { Processor } from 'unified';

type Node = {
  type: string;
  referenceType?: string;
  children?: Node[];
  position?: { start: { offset?: number }; end: { offset?: number } };
};

const LITERAL = new Set(['code', 'inlineCode', 'html', 'definition', 'image', 'imageReference']);

const CONTAINERS = String.raw`[ \t]*(?:>[ \t]*|(?:[-*+]|\d{1,9}[.)])[ \t]+)*`;
const LINE_END = String.raw`[ \t]*(?=\r?\n|$)`;
const NEXT_LINE = String.raw`\n(?![ \t>]*(?:\r?\n|\0))`;                                // not a blank line, nor a code block's
const FENCE_LINE = new RegExp(String.raw`((?:^|\n)${CONTAINERS})\$\$(?=${LINE_END})`, 'g');
const PIECES = new RegExp([
  String.raw`\\[^([\n]`,                                                              // any other escape: what follows is text
  String.raw`(^|\n)(${CONTAINERS})(?:` + [
    String.raw`\\\[((?:[^\\\n]|\\[^[\]\n]|${NEXT_LINE}){1,4096})\\\]${LINE_END}`,      // \[ that fills its lines
    String.raw`\$\$((?:[^$\n]|${NEXT_LINE}){1,4096})\$\$${LINE_END}`,                  // $$ with text, closed at a line's end
    String.raw`\$\$(?=[ \t]*[^\s$][^\n$]*(?:\n|$))`,                                  // $$ with text, not closed
  ].join('|') + ')',
  String.raw`(?:^|\n)${CONTAINERS}\$\$${LINE_END}`,                                   // a fence's own line
  String.raw`\$\$[^$\n]*(?:(?:\n(?!${CONTAINERS}(?:\r?\n|\$\$))|\$(?!\$))[^$\n]*)*\$\$`,  // a formula in a line: its text is its own
  String.raw`(\$\$)`,                                                                 // a stray, which must not pair with a new $$
  String.raw`\\\(((?:[^\\\n$]|\\[^()\n]|\$(?!\$)){1,4096})\\\)`,
].join('|'), 'g');

/**
 * A fence on its own lines, or undefined if it can't stand. A line that falls out of the opening line's container would leave the
 * fence running on to the end of the reply, and a next line indented past it would turn from a paragraph's text into code.
 */
function fenced(containers: string, body: string, next: string): string | undefined {
  const inside = containers.replace(/[^ \t>]/g, ' ');
  const lines = body.split('\n');
  const rest = lines.slice(1);
  if (rest.some((line) => !line.startsWith(inside))) return undefined;
  if (/^(?: {4}| {0,3}\t)/.test(next.startsWith(inside) ? next.slice(inside.length) : next)) return undefined;
  const opening = lines[0].trim();
  const closing = rest.length ? rest[rest.length - 1].slice(inside.length).trim() : '';
  return [
    `${containers}$$`,
    ...(opening ? [inside + opening] : []),
    ...rest.slice(0, -1),
    ...(closing ? [inside + closing] : []),
    `${inside}$$`,
  ].join('\n');
}

/** The text with every piece found in the mask rewritten. The mask has the text's length, so a match there is a span of the text. */
function rewrite(text: string, mask: string, isBlockStart: (offset: number) => boolean, strayAs: string): string {
  let out = '';
  let copied = 0;
  const swap = (from: number, to: number, replacement: string) => {
    out += text.slice(copied, from) + replacement;
    copied = to;
  };
  for (let m = PIECES.exec(mask); m; m = PIECES.exec(mask)) {
    const [whole, start, containers, display, dollars, stray, inline] = m;
    const end = m.index + whole.length;
    if (inline !== undefined) swap(m.index, end, `$$${text.slice(m.index + 2, end - 2)}$$`);
    else if (stray !== undefined) swap(m.index, end, strayAs);
    else if (containers !== undefined) {
      const opener = m.index + start.length + containers.length;
      const body = display ?? dollars;
      if (body === undefined) swap(opener, opener + 2, '\\$\\$');
      // A number on a paragraph's later line is its text, unless the parser started a list there.
      else if (!/[^ \t>]/.test(containers) || isBlockStart(opener)) {
        const lineEnd = text.indexOf('\n', end + 1);
        const block = fenced(containers, text.slice(opener + 2, opener + 2 + body.length), text.slice(end + 1, lineEnd < 0 ? text.length : lineEnd));
        if (block) swap(m.index, end, start + block);
        else if (display !== undefined || body.includes('\n')) {
          // Not a formula after all, so what's inside it is still to read, and a $$ with text on its line would lose that text.
          if (display === undefined && body.split('\n')[0].trim()) swap(opener, opener + 2, '\\$\\$');
          PIECES.lastIndex = opener + 2;
        }
      }
    }
  }
  return out + text.slice(copied);
}

export function texDelimiters(text: string, parse: (doc: string) => Node): string {
  // Nothing to rewrite even if nothing were literal: most replies, and any run of openers with no closer, never pay for the parse.
  // A stray alone doesn't count: it only matters beside a new $$, and a formula still streaming has one on most tokens.
  if (rewrite(text, text, () => true, '$$') === text) return text;

  let mask = '';
  const blank = (from: number, to: number) => { mask += text.slice(mask.length, from) + text.slice(from, to).replace(/[^\n]/g, '\0'); };
  const blockStarts = new Set<number>();
  const walk = (node: Node) => {
    if (!node.position) return;                                                        // a link made by a transform, from text already seen
    const from = node.position.start.offset!;
    const to = node.position.end.offset!;
    if (LITERAL.has(node.type) || (node.type === 'link' && text[from] !== '[') || (node.type === 'linkReference' && node.referenceType !== 'full')) {
      blank(from, to);                                                                 // a bare URL, or a label that must match its definition
      return;
    }
    if (node.type === 'paragraph' || node.type === 'heading') blockStarts.add(from);
    node.children?.forEach(walk);
    if (node.type === 'link' || node.type === 'linkReference') {
      const last = node.children?.[node.children.length - 1];
      blank(last?.position?.end.offset ?? from, to);                                   // [text] stays readable; (target) doesn't
    }
  };
  // A fence's own line reads as a block of one line, as an empty heading, so the next line isn't its paragraph's. Any other $$ is <,
  // which ends a bare URL, so that a URL doesn't take a closing $$.
  walk(parse(text.replace(FENCE_LINE, '$1##').replaceAll('$$', '<<')));
  mask += text.slice(mask.length);
  return rewrite(text, mask, (offset) => blockStarts.has(offset), '\\$\\$');
}

/** The remark plugin: the app's own parser, with this pass ahead of it. */
export function remarkTexDelimiters(this: Processor) {
  const parse = this.parser!;
  this.parser = (doc, file) => parse(texDelimiters(doc, (d) => parse(d, file)), file);
}

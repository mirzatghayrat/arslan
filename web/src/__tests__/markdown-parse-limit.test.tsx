/**
 * The Markdown parser is quadratic in the delimiters of one inline run, and a reply is text outside content can steer: a reply
 * that would freeze the window is shown as written instead of being parsed.
 * - the scan calls no parser, and it never reads less inline than the parser would (the differential below);
 * - ordinary long replies, however big, are still formatted;
 * - a reply crossing the limit while it streams switches to plain text once, and stays there.
 */
import { cleanup, render } from '@testing-library/react';
import React from 'react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkParse from 'remark-parse';
import { unified } from 'unified';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
  Trans: ({ children }: { children?: unknown }) => children,
}));

import Markdown from '../components/Markdown';
import { splitBlocks } from '../lib/markdownBlocks';
import { COST_LIMIT, markdownCost, tooCostlyToParse } from '../lib/markdownCost';

afterEach(cleanup);

const here = dirname(fileURLToPath(import.meta.url));
const fill = (s: string, n: number) => s.repeat(Math.ceil(n / s.length)).slice(0, n);
const KB = 1024;
const BOM = String.fromCharCode(0xFEFF);

const HOSTILE: Record<string, string> = {
  'brackets': fill('[', 16 * KB),
  'images': fill('![', 16 * KB),
  'emphasis': fill('*a', 16 * KB),
  'underscores': fill('_a_ ', 32 * KB),
  'strikethrough': fill('~a', 16 * KB),
  'links never closed': fill('[a](', 32 * KB),
  'references': fill('[a][', 32 * KB),
  'footnotes': fill('[^a]', 32 * KB),
  'table columns': `${fill('|a', 16 * KB)}\n${fill('|-', 16 * KB)}\n`,
  'a run split over lines': fill('*a\n', 32 * KB),
  'a run split over CRLF lines': fill('*a\r\n', 32 * KB),
  'many paragraphs that add up': fill(`${'*a'.repeat(500)}\n\n`, 64 * KB),
  'one table cell': `| a |\n|---|\n| ${fill('*a', 16 * KB)} |\n`,
  'a table that is not one': `a|b|c\n-|-\n${fill('*a\n', 32 * KB)}`,
};

const ORDINARY: Record<string, string> = {
  'a long mixed reply': fill('## Heading\n\nA paragraph of **bold** and *italic* words, a [link](https://a.example/x_y), `code`.\n\n```json\n{"a": [1, 2, {"b": "c"}]}\n```\n\n1. one\n2. two\n\n> quoted\n\n', 256 * KB),
  'a huge JSON fence': `\`\`\`json\n${fill('{"k":[1,2,{"a":"b"}]},', 256 * KB)}\n\`\`\`\n`,
  'code with no blank lines': `\`\`\`python\n${fill('def f(a_b, c_d): return a_b[c_d] * 2\n', 256 * KB)}\`\`\`\n`,
  'a fence right after a line of text': `Here it is:\n\`\`\`\n${fill('[*_', 64 * KB)}\n\`\`\`\n\nAfter.\n`,
  'a tilde fence': `~~~\n${fill('[*_', 64 * KB)}\n~~~\n`,
  'a fence still streaming': `\`\`\`\n${fill('[*_', 64 * KB)}`,
  'snake_case prose': fill('the some_variable and other_name are used, see item_one and item_two.\n\n', 256 * KB),
  'a 200-row table with bold and links': `| a | b |\n|---|---|\n${'| **x** | [y](https://a.example) |\n'.repeat(200)}`,
  'nesting a real reply might have': `${'> '.repeat(20)}quoted\n\n${'- '.repeat(20)}item\n\n${'1. '.repeat(20)}item\n`,
};

describe('what is too costly', () => {
  it.each(Object.keys(HOSTILE))('%s', (name) => expect(tooCostlyToParse(HOSTILE[name])).toBe(true));
  it.each(Object.keys(ORDINARY))('not: %s', (name) => expect(tooCostlyToParse(ORDINARY[name])).toBe(false));

  it('nesting past 100 is too costly, however the line nests, and 100 is not', () => {
    for (const marker of ['>', '> ', '- ', '* ', '+ ', '-\t', '1. ', '123) ']) {
      const nest = (n: number) => `${marker.repeat(n)}a\n`;
      expect(tooCostlyToParse(nest(100)), `${marker} at 100`).toBe(false);
      expect(tooCostlyToParse(nest(101)), `${marker} at 101`).toBe(true);
    }
  });

  it('the limit is on the run squared, and a blank line ends a run', () => {
    const side = Math.sqrt(COST_LIMIT);
    expect(tooCostlyToParse('*'.repeat(side))).toBe(false);
    expect(tooCostlyToParse('*'.repeat(side + 1))).toBe(true);
    expect(markdownCost(`${'*'.repeat(10)}a\n\n${'*'.repeat(10)}a`)).toBe(200);
    expect(markdownCost(`${'*'.repeat(10)}a\n \t\n${'*'.repeat(10)}a`)).toBe(200);
    expect(markdownCost(`${'*'.repeat(10)}a\n${'*'.repeat(10)}a`)).toBe(400);
  });

  it('a bracket costs four delimiters, and so does its pair', () => {
    expect(markdownCost('[[')).toBe(64);
    expect(markdownCost(']]')).toBe(64);
    expect(markdownCost('*_~')).toBe(9);
  });

  it('pipes count per line, since a table parses its rows apart', () => {
    expect(markdownCost(`${'|'.repeat(10)}\n${'|'.repeat(10)}`)).toBe(200);
  });

  it('a run before a fence still counts, and the limit is exact', () => {
    expect(tooCostlyToParse(`${fill('*a', 16 * KB)}\n\`\`\`\nx\n\`\`\`\n`)).toBe(true);
    expect(tooCostlyToParse(`${'*'.repeat(Math.sqrt(COST_LIMIT))}a\n\n|`)).toBe(true);
  });

  it('does not nest deep inside a fence', () => {
    expect(tooCostlyToParse(`\`\`\`\n${'> '.repeat(500)}\n\`\`\`\n`)).toBe(false);
  });
});

describe('a code fence only counts when the parser would agree', () => {
  const PAYLOAD = fill('*a', 16 * KB);
  const skipped = (doc: string) => !tooCostlyToParse(doc);

  it('a closed fence ends where the parser ends it', () => {
    expect(skipped(`\`\`\`\n${PAYLOAD}\n\`\`\`\n`)).toBe(true);
    expect(skipped(`\`\`\`\n\`\`\`\n${PAYLOAD}`)).toBe(false);
    expect(skipped(`\`\`\`\n\`\`\`  \n${PAYLOAD}`)).toBe(false);
    expect(skipped(`\`\`\`\n   \`\`\`\n${PAYLOAD}`)).toBe(false);
  });

  it('what does not close it leaves it open', () => {
    expect(skipped(`\`\`\`\`\n\`\`\`\n${PAYLOAD}`)).toBe(true);        // too short
    expect(skipped(`\`\`\`\n~~~\n${PAYLOAD}`)).toBe(true);             // another character
    expect(skipped(`\`\`\`\n\`\`\` a\n${PAYLOAD}`)).toBe(true);        // has text after it
    expect(skipped(`\`\`\`\n    \`\`\`\n${PAYLOAD}`)).toBe(true);      // indented too far
  });

  it.each([
    ['a backtick in its info string', `\`\`\` a\`b\n${PAYLOAD}\n`],
    ['too short', `\`\`\n${PAYLOAD}\n`],
    ['inside a list item, which an unindented line ends', `- a\n  \`\`\`\n${PAYLOAD}\n`],
    ['after an indented fence, whose closing line looks like an opening', `  \`\`\`\nx\n\`\`\`\n${PAYLOAD}\n`],
    ['after a fence in a quote', `> \`\`\`\n> x\n\`\`\`\n${PAYLOAD}\n\`\`\`\n`],
    ['after one behind a byte order mark, which the parser drops', `${BOM}\`\`\`\n\`\`\`\n${PAYLOAD}\n`],
    ['inside a quote, which an unmarked line ends', `> \`\`\`\n${PAYLOAD}\n`],
    ['indented, so maybe code and maybe not', `  \`\`\`\n${PAYLOAD}\n`],
    ['after an HTML block', `<div>\n\`\`\`\n\n${PAYLOAD}\n`],
    ['after an HTML comment, which runs over blank lines', `<!--\n\n\`\`\`\n\n-->\n\n${PAYLOAD}\n\n\`\`\`\n`],
    ['an HTML block in a list', `- <div>\n\`\`\`\n\n${PAYLOAD}\n`],
    ['in a definition\'s title', `[a]: b "\n\`\`\`\n"\n\n${PAYLOAD}\n\n\`\`\`\n`],
    ['in a footnote definition', `[^a]: b\n\`\`\`\n\n${PAYLOAD}\n`],
    ['in a math block', `$$\n\`\`\`\n$$\n\n${PAYLOAD}\n`],
    ['in a TeX block, which the pre-pass makes math', `\\[\n\`\`\`\n\\]\n\n${PAYLOAD}\n`],
  ])('not a fence, or not one to believe: %s', (_name, doc) => expect(skipped(doc)).toBe(false));

  it.each([0xA0, 0x0B, 0x0C, 0x2028, 0x3000, 0xFEFF])('white space with character code %i after a fence does not close it, for the parser or the scan', (code) => {
    const other = String.fromCharCode(code);
    expect(skipped(`\`\`\`\n\`\`\`${other}\n\`\`\`\n${PAYLOAD}\n`)).toBe(false);
    expect(skipped(`~~~\n~~~${other}\n~~~\n${PAYLOAD}\n`)).toBe(false);
  });

  it('a space or a tab after a fence still closes it', () => {
    expect(skipped(`\`\`\`\n\`\`\` \t\n${PAYLOAD}\n`)).toBe(false);
    expect(skipped(`\`\`\`\n${PAYLOAD}\n\`\`\` \t\n`)).toBe(true);
  });

  it.each(['+ ', '* ', '- ', '1. ', '2) ', '   + ', '+\t', '> ', '>'])('a line of only %j does not end a run', (marker) => {
    let doc = '';
    while (doc.length < 64 * KB) doc += `${'*a'.repeat(100)}\n${marker}\n`;
    expect(tooCostlyToParse(doc)).toBe(true);
  });

  it('a list marker made of a delimiter still counts', () => {
    expect(markdownCost('*a\n* \n*a')).toBe(9);
  });

  it('a lone carriage return ends a line, as it does for the parser', () => {
    expect(skipped(`\`\`\`\rx\r\`\`\`\r${PAYLOAD}`)).toBe(false);
    expect(markdownCost(`${'*'.repeat(10)}a\r\r${'*'.repeat(10)}a`)).toBe(200);
  });

  // The limit is safe only if the scan never reads less inline than the parser does. Lines that change what a fence means, in a
  // seeded random order, against the parser the app uses. (The TeX pre-pass rewrites offsets, so it has its own case above.)
  it('never reads less inline than the real parser, over many generated documents', () => {
    const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath, { singleDollarTextMath: false });
    const LINES = [
      // A hole needs what hides a fence, a fence, and then something to read inline, so those come up often.
      '```', '```', '```', '```', '', '', '', '', '*a*a', '*a*a', '*a*a', '*a*a', '*a*a', '[[', '[[', `${BOM}\`\`\``,
      ...[0xA0, 0x0B, 0x0C, 0x2028, 0x3000, 0xFEFF].flatMap((code) => [`\`\`\`${String.fromCharCode(code)}`, `~~~${String.fromCharCode(code)}`]),
      '+ ', '* ', '- ', '1. ', '1) ', '   + ', '+\t', '-\t', '> ',
      '```', '````', '~~~', '``` py', '```a`b', '  ```', '    ```', '   ```', '> ```', '- ```', '-   ```', '1. ```', '`', '``',
      '<div>', '</div>', '<!--', '-->', '<script>', '</script>', '<?', '?>', '<a>', '<![CDATA[', ']]>', '<!X', '$$', '$$ x', '  $$', '> $$',
      '[a]: b', '[a]: b "', '[a]:', '"', "'", '(', ')', '[^a]: b', '    x', '  - a', '- a', '> a', '>', '1. a', '---', '===', '# h',
      '| a |', '|---|', 'a|b', '-|-', '', '', '', 'text', '*a*a', '[[', '_a_', '~~a', '\t```', ' ', '\\', '```\r', '\r',
    ];
    let seed = 20261107;
    const next = (n: number) => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed % n; };
    const isOpener = (c: string) => c === '*' || c === '_' || c === '~' || c === '[' || c === ']';
    type Node = { type: string; children?: Node[]; position?: { start: { offset?: number }; end: { offset?: number } } };
    for (let round = 0; round < 20000; round++) {
      const doc = Array.from({ length: 2 + next(10) }, () => LINES[next(LINES.length)]).join('\n');
      let parsed = 0;
      const walk = (node: Node) => {
        if ((node.type === 'paragraph' || node.type === 'heading' || node.type === 'tableCell') && node.position) {
          const opens = Array.from(doc.slice(node.position.start.offset, node.position.end.offset)).filter(isOpener).length;
          parsed += opens * opens;
        } else node.children?.forEach(walk);
      };
      walk(parser.parse(doc) as Node);
      expect(markdownCost(doc), JSON.stringify(doc)).toBeGreaterThanOrEqual(parsed);
    }
  }, 120_000);
});

describe('the scan itself', () => {
  it('stays linear on the worst input it can get', () => {
    const start = performance.now();
    for (const doc of Object.values(HOSTILE)) tooCostlyToParse(doc);
    for (const doc of Object.values(ORDINARY)) tooCostlyToParse(doc);
    expect(performance.now() - start).toBeLessThan(5000);
  });

  it('calls no parser', () => {
    const src = readFileSync(resolve(here, '../lib/markdownCost.ts'), 'utf8');
    expect(src).not.toMatch(/^import /m);
  });
});

describe('what the reader sees', () => {
  const PLAIN = `*bold* and [a link](https://a.example) ${fill('*a', 16 * KB)}`;

  it('too costly: exactly the text, wrapped, with nothing parsed', () => {
    const { container } = render(<Markdown className="mine">{PLAIN}</Markdown>);
    const box = container.firstElementChild as HTMLElement;
    expect(box.className).toBe('mine');
    expect(box.textContent).toBe(PLAIN);
    expect(box.style.whiteSpace).toBe('pre-wrap');
    expect(box.style.overflowWrap).toBe('anywhere');
    expect(container.querySelector('em, strong, a, p')).toBeNull();
  });

  it('it is still ordinary text to React, so nothing in it can become markup', () => {
    const doc = `<img src=x onerror=alert(1)> ${fill('*a', 16 * KB)}`;
    const { container } = render(<Markdown>{doc}</Markdown>);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toBe(doc);
  });

  it('ordinary: formatted as before', () => {
    const { container } = render(<Markdown>{'*bold* and [a link](https://a.example)'}</Markdown>);
    expect(container.querySelector('em')).not.toBeNull();
    expect(container.querySelector('a')).not.toBeNull();
  });

  it('a reply that crosses the limit while streaming switches once, and only the block that crossed', () => {
    const Stream = ({ text }: { text: string }) => (
      <div>{splitBlocks(text).map((block, i) => <Markdown key={i} className="contents">{block}</Markdown>)}</div>
    );
    const first = 'A *first* paragraph.\n\n';
    const whole = `${first}${fill('*a', 16 * KB)}`;
    const { container, rerender } = render(<Stream text={first} />);
    const switches: number[] = [];
    let plainBefore = false;
    for (let at = first.length; at <= whole.length; at += 512) {
      const text = whole.slice(0, at);
      rerender(<Stream text={text} />);
      const plain = (container.querySelectorAll('.contents')[1] as HTMLElement | undefined)?.style.whiteSpace === 'pre-wrap';
      if (plain !== plainBefore) switches.push(at);
      plainBefore = plain;
      expect(container.querySelector('em')?.textContent).toBe('first');
    }
    expect(switches).toHaveLength(1);
    expect(plainBefore).toBe(true);
    expect((container.querySelectorAll('.contents')[1] as HTMLElement).textContent).toBe(whole.slice(first.length));
  }, 60_000);
});

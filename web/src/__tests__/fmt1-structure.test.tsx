/**
 * FMT1 PR 2 (0.1.64): a reply's structure catches up with the iPhone mock. One fixture reply with every element, then what
 * each must do:
 * - a formula is typeset by KaTeX into nodes it builds itself, never from an HTML string, and a single `$` is never math;
 * - a broken or half-streamed formula, one over the size cap and one that defines macros show their source as text, not a red error;
 * - the rewrite ahead of the parser changes formulas only: never code, a link's target, a list's numbers or the text around them;
 * - a reply can't paint outside its own box;
 * - a formula that hasn't changed is not typeset again while a reply streams;
 * - lists: a number or a dot, never both, and a hollow dot one level down;
 * - task checkboxes are read-only; tables keep the alignment the Markdown asked for.
 */
import { cleanup, render, waitFor } from '@testing-library/react';
import katex from 'katex';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkParse from 'remark-parse';
import { unified } from 'unified';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
  Trans: ({ children }: { children?: unknown }) => children,
}));

import Formula from '../components/Formula';
import Markdown from '../components/Markdown';
import { buildStandaloneHtml } from '../components/MessageBody';
import { texDelimiters } from '../lib/texDelimiters';

const here = dirname(fileURLToPath(import.meta.url));
// The slow-formula budget is the window's, and this file is one window: on a loaded machine, real time would spend it.
beforeEach(() => { vi.spyOn(performance, 'now').mockReturnValue(0); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const REPLY = `# Clearing Downloads

The energy is $$E = mc^2$$ here, and \\(a^2 + b^2\\) there.

$$
\\sum_i s_i \\approx 1.8
$$

\\[
\\frac{1}{2}
\\]

- Installers
  - Keep the newest
- Photos

1. First
2. Second

- [x] Compared
- [ ] Moved to the Trash

| Type | Count | Size |
|:-----|:----:|-----:|
| dmg  | 5     | 1.2  |
`;

const show = (text: string) => render(<Markdown>{text}</Markdown>).container;
const typeset = (root: ParentNode) => root.querySelectorAll('.katex');
const katexLoaded = async () => {
  await waitFor(() => expect(typeset(show('ready: $$x$$'))).toHaveLength(1));
  cleanup();
};
const sheet = () => readFileSync(resolve(here, '../index.css'), 'utf8');

// The app's own parser, so these tests read a reply as the app does.
const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath, { singleDollarTextMath: false });
const parse = (doc: string) => parser.parse(doc);
const rewrite = (text: string) => texDelimiters(text, parse);

describe('formulas', () => {
  it('typesets every delimiter, inline and on its own line, and no others', async () => {
    const c = show(REPLY);
    await waitFor(() => expect(typeset(c)).toHaveLength(4));
    expect(c.querySelectorAll('.katex-display')).toHaveLength(2);
    expect(c.textContent).not.toContain('$$');
    expect(c.textContent).not.toContain('\\[');
    expect(c.textContent).not.toContain('\\(');
  });

  it.each([
    ['prices', 'It costs $5 and $10 today.'],
    ['one word', 'Set $HOME and $PATH first.'],
    ['a formula in single dollars, a known limit', 'The area is $x^2$ here.'],
  ])('a single dollar is never math: %s', async (_, text) => {
    const c = show(text);
    await new Promise((r) => setTimeout(r, 50));
    expect(typeset(c)).toHaveLength(0);
    expect(c.textContent).toBe(text);
  });

  it('leaves code alone, fenced and inline', async () => {
    const c = show('Use `\\(x\\)` and `$$y$$`.\n\n```latex\n\\[ z \\]\n$$ w $$\n```\n');
    await new Promise((r) => setTimeout(r, 50));
    expect(typeset(c)).toHaveLength(0);
    expect(c.querySelector('pre')!.textContent).toBe('\\[ z \\]\n$$ w $$\n');
    expect(c.querySelector('p')!.textContent).toBe('Use \\(x\\) and $$y$$.');
  });

  it('a ```math fence stays a code block: only the delimiters make a formula', async () => {
    const c = show('```math\nx^2\n```\n');
    await new Promise((r) => setTimeout(r, 50));
    expect(typeset(c)).toHaveLength(0);
    expect(c.querySelector('[data-testid=code-lang]')!.textContent).toBe('math');
  });

  it('broken TeX shows its source as text, with no red error', async () => {
    await waitFor(() => expect(typeset(show('ready: $$x$$'))).toHaveLength(1));   // KaTeX is loaded from here on
    cleanup();
    const c = show('The start of $$\\frac{1}{$$ a formula.');
    expect(typeset(c)).toHaveLength(0);
    expect(c.textContent).toContain('\\frac{1}{');
    expect(c.querySelector('.katex-error')).toBeNull();
  });

  it('a formula over 4 KiB is plain text, and one at the limit is typeset', async () => {
    await waitFor(() => expect(typeset(show('ready: $$x$$'))).toHaveLength(1));
    cleanup();
    const at = 'x'.repeat(4096);
    expect(typeset(show(`$$${at}$$`))).toHaveLength(1);
    cleanup();
    const over = show(`$$${at}x$$`);
    expect(typeset(over)).toHaveLength(0);
    expect(over.textContent).toBe(`${at}x`);
  });

  it('once slow formulas have cost a second, the rest stay plain text, and ordinary ones never count', async () => {
    vi.resetModules();                                                       // the budget is the window's: a fresh one
    const { default: Fresh } = await import('../components/Formula');
    const { default: K } = await import('katex');
    let clock = 0;
    vi.spyOn(performance, 'now').mockImplementation(() => clock);
    const ms = { each: 49 };
    vi.spyOn(K, 'render').mockImplementation((tex: string, el: HTMLElement) => { clock += ms.each; el.textContent = `typeset ${tex}`; });
    const one = async (tex: string) => {
      const { container } = render(<Fresh tex={tex} />);
      await waitFor(() => expect(container.textContent).toMatch(new RegExp(`${tex}$`)));
      await new Promise((r) => setTimeout(r, 0));
      return container.textContent;
    };
    await one('ready');
    for (let i = 0; i < 30; i += 1) expect(await one(`fast${i}`)).toBe(`typeset fast${i}`);     // 1.5 s of formulas under 50 ms
    ms.each = 500;
    expect(await one('slow1')).toBe('typeset slow1');
    expect(await one('slow2')).toBe('typeset slow2');                         // the second brings it to 1,000 ms
    expect(await one('after')).toBe('after');
    expect(K.render).not.toHaveBeenCalledWith('after', expect.anything(), expect.anything());
  });

  it('is told to trust nothing: no links or images from a formula', async () => {
    await waitFor(() => expect(typeset(show('ready: $$x$$'))).toHaveLength(1));
    cleanup();
    const c = show('$$\\href{https://example.org}{x}$$ and $$\\includegraphics{https://example.org/a.png}$$');
    expect(c.querySelector('a')).toBeNull();
    expect(c.querySelector('img')).toBeNull();
    const render_ = vi.spyOn(katex, 'render');
    show('$$y$$');
    expect(render_.mock.calls[0][2]).toMatchObject({ trust: false, throwOnError: true });
  });

  it('the window never builds a formula from an HTML string, and KaTeX is its own chunk', () => {
    const source = readFileSync(resolve(here, '../components/Formula.tsx'), 'utf8');
    expect(source).not.toMatch(/dangerouslySetInnerHTML|innerHTML|renderToString/);
    expect(source).not.toMatch(/^import (?!type )[^\n]*katex/m);
    expect(source).toMatch(/import\('katex'\)/);
    const markdown = readFileSync(resolve(here, '../components/Markdown.tsx'), 'utf8');
    expect(markdown).not.toMatch(/^import [^\n]*katex/m);
  });

  it('while a reply streams, a formula that has not changed is not typeset again', async () => {
    await waitFor(() => expect(typeset(show('ready: $$x$$'))).toHaveLength(1));
    cleanup();
    const render_ = vi.spyOn(katex, 'render');
    const first = 'One $$a^2$$ and two $$b^2$$';
    const view = render(<Markdown>{first}</Markdown>);
    expect(render_).toHaveBeenCalledTimes(2);
    view.rerender(<Markdown>{`${first} and more`}</Markdown>);
    view.rerender(<Markdown>{`${first} and more words`}</Markdown>);
    expect(render_).toHaveBeenCalledTimes(2);
    view.rerender(<Markdown>{`${first} and $$c^2$$`}</Markdown>);
    expect(render_).toHaveBeenCalledTimes(3);
  });

  it('an exported .html, which has no KaTeX stylesheet, shows the browser\'s own math', () => {
    expect(buildStandaloneHtml('<p>x</p>', 't')).toMatch(/\.katex-html\s*\{\s*display:\s*none/);
  });

  it('the stylesheet comes with KaTeX, in the same chunk', () => {
    expect(readFileSync(resolve(here, '../components/Formula.tsx'), 'utf8')).toMatch(/import\('katex\/dist\/katex\.min\.css'\)/);
  });

  it('a command trust refuses shows no red: nothing in a reply looks like an alarm', async () => {
    await katexLoaded();
    const c = show('$$\\href{https://example.org}{x}$$');
    expect(c.querySelector('[style*="cc0000"]')).toBeNull();
    expect(c.querySelector('a')).toBeNull();
    expect(c.querySelector('[style*="currentColor"]')).not.toBeNull();
  });

  it('copying a selected formula gives its TeX, not its garbled reading', async () => {
    await katexLoaded();
    const c = show('The energy $$E = mc^2$$');
    const selection = window.getSelection()!;
    selection.selectAllChildren(c.querySelector('.katex')!);
    const clipboard = new Map<string, string>();
    const copy = Object.assign(new Event('copy', { cancelable: true }), {
      clipboardData: { setData: (kind: string, value: string) => { clipboard.set(kind, value); } },
    });
    document.dispatchEvent(copy);
    selection.removeAllRanges();
    expect(clipboard.get('text/plain')).toContain('E = mc^2');
    expect(copy.defaultPrevented).toBe(true);
  });

  it('KaTeX failing to load leaves the source showing, and raises nothing', async () => {
    vi.resetModules();
    vi.doMock('katex', () => { throw new Error('the chunk did not load'); });
    const unhandled: unknown[] = [];
    const note = (reason: unknown) => { unhandled.push(reason); };
    process.on('unhandledRejection', note);
    try {
      const { default: Fresh } = await import('../components/Formula');
      const { container } = render(<Fresh tex="x^2" />);
      await new Promise((r) => setTimeout(r, 50));
      expect(container.textContent).toBe('x^2');
      expect(unhandled).toEqual([]);
    } finally {
      process.off('unhandledRejection', note);
      vi.doUnmock('katex');
      vi.resetModules();
    }
  });

  it('a code fence is a formula only by its class, not because its language contains the word', () => {
    const c = show('```math-display-x\nx^2\n```\n');
    expect(c.querySelector('.md-math')).toBeNull();
    expect(c.querySelector('[data-testid=code-lang]')!.textContent).toBe('math-display-x');
  });
});

describe('a formula that defines macros never reaches KaTeX', () => {
  const body = 'x'.repeat(1600);
  it.each([
    ['\\def', `\\def\\b{${body}}${'\\b'.repeat(100)}`],
    ['\\gdef', '\\gdef\\b{x}\\b'],
    ['\\edef', '\\edef\\b{x}\\b'],
    ['\\xdef', '\\xdef\\b{x}\\b'],
    ['\\let', '\\let\\b=x\\b'],
    ['\\futurelet', '\\futurelet\\b\\c\\d'],
    ['\\newcommand', '\\newcommand{\\b}{x}\\b'],
    ['\\newcommand*', '\\newcommand*{\\b}{x}\\b'],
    ['\\renewcommand', '\\renewcommand{\\sum}{x}\\sum'],
    ['\\providecommand', '\\providecommand{\\b}{x}\\b'],
    ['\\global', '\\global\\def\\b{x}\\b'],
    ['\\long', '\\long\\def\\b{x}\\b'],
  ])('%s', async (_, tex) => {
    await katexLoaded();
    const render_ = vi.spyOn(katex, 'render').mockImplementation(() => {});     // mocked: unfixed, the first case freezes for minutes
    const { container } = render(<Formula tex={tex} />);
    expect(render_).not.toHaveBeenCalled();
    expect(container.textContent).toBe(tex);
  });

  it.each(['\\longrightarrow', '\\longleftarrow x', '\\lessgtr'])('%s is not a definition', async (tex) => {
    await katexLoaded();
    const { container } = render(<Formula tex={tex} />);
    expect(typeset(container)).toHaveLength(1);
  });
});

describe('a reply cannot paint outside its own box', () => {
  it('the root clips what a formula moves or widens, in old WebKit too', () => {
    const root = show('$$\\kern-40em x$$').firstElementChild!;
    expect(root.classList.contains('md-root')).toBe(true);
    expect(sheet()).toMatch(/\.md-root\s*\{\s*overflow:\s*hidden;\s*overflow:\s*clip;/);
  });

  it('a long word or URL wraps, since nothing can scroll to it now', () => {
    expect(sheet()).toMatch(/\.md-root\s*\{[^}]*overflow-wrap:\s*break-word;/);
  });

  it('one rule can\'t push the rest of the chat out of reach: height stays in flow, so the clip doesn\'t bound it', async () => {
    await katexLoaded();
    const c = show('A reply $$\\rule{1em}{100000000em}$$ here.');
    expect(c.querySelector<HTMLElement>('.katex-rule')!.style.borderTopWidth).toBe('50em');
  });

  it('keeps the class it was given', () => {
    expect(render(<Markdown className="extra">x</Markdown>).container.firstElementChild!.className).toBe('md-root extra');
  });
});

describe('texDelimiters', () => {
  it.each([
    ['\\(x\\)', '$$x$$'],
    ['a \\(x\\) b \\(y\\) c', 'a $$x$$ b $$y$$ c'],
    ['literal \\\\(x\\\\) stays', 'literal \\\\(x\\\\) stays'],
    ['\\\\(x\\)', '\\\\(x\\)'],                                                     // an escaped backslash, then text
    ['an unclosed \\(x stays', 'an unclosed \\(x stays'],
    ['\\(two\nlines\\)', '\\(two\nlines\\)'],
    ['**\\(x\\)** and [\\(y\\)](u)', '**$$x$$** and [$$y$$](u)'],
    ['\\(f[0,1](x)\\)', '$$f[0,1](x)$$'],                                                // TeX that looks like a link
    ['\\(a `b` c\\)', '$$a `b` c$$'],
    ['[https://e.org \\(x\\)', '[https://e.org $$x$$'],                                 // a link a transform made, with no position
    [`\\(${'x'.repeat(4096)}\\)`, `$$${'x'.repeat(4096)}$$`],
    [`\\(${'x'.repeat(4097)}\\)`, `\\(${'x'.repeat(4097)}\\)`],
  ])('inline: %j', (from, to) => { expect(rewrite(from)).toBe(to); });

  it.each([
    '`\\(x\\)`',
    '``\\(x\\)``',
    '`a\\(x``y\\)`',
    '```\n\\[x\\]\n```',
    '  ```\n  \\(x\\)\n  ```',
    '```\nan unclosed fence \\(x\\)',
    '> ~~~\n> \\(x\\)\n> ~~~',
    '- ~~~\n  \\(x\\)\n  ~~~',
    '1. ~~~\n   \\[x\\]\n   ~~~',
    '    \\(x\\)',
    '\t\\[x\\]',
    'text\n\n    \\[x\\]\n\n    \\(y\\)',
    '- a\n\n      \\(x\\)',                              // indented code inside an item
    '> a\n>\n>     \\(x\\)',
    '[a](u\\(1\\))',
    '[a](u\\(1\\) "t\\(2\\)")',
    '[a](<u \\(1\\)>)',
    '![a](u\\(1\\))',
    '[r]: d\\(1\\) "t\\(2\\)"',
    '[\\(x\\)]\n\n[\\(x\\)]: u',                         // a label that must still match its definition
    '[\\(x\\)][]\n\n[\\(x\\)]: u',
    '![\\(x\\)][r]\n\n[r]: u',
    '$$\nx\n$$\n    \\(y\\)',                              // code after a fence, not a paragraph's next line
    'https://e.org/\\(1\\)',
    '<https://e.org/\\(1\\)>',
    '<b title="\\(1\\)">',
    '$$\n\\(x\\)\n$$',                                 // a formula's own text
    'a $$ \\(x\\) $$ b',
  ])('what Markdown reads literally stays: %j', (text) => { expect(rewrite(text)).toBe(text); });

  it.each([
    ['~~~\n\\(x\\)\n~~~\n\\(y\\)', '~~~\n\\(x\\)\n~~~\n$$y$$'],
    ['~~~\n\\(x\\)\n~~~~\n\\(y\\)', '~~~\n\\(x\\)\n~~~~\n$$y$$'],                     // a longer closer still closes it
    ['> ~~~\n> \\(x\\)\n\n\\(y\\)', '> ~~~\n> \\(x\\)\n\n$$y$$'],                   // the quote ended the fence
    ['a ` b\n\n\\(x\\)\n\nc ` d', 'a ` b\n\n$$x$$\n\nc ` d'],                         // no code span across blocks
    ['- a\n\n    \\(x\\)', '- a\n\n    $$x$$'],                                       // an item's paragraph, not code
    ['[\\(x\\)][r]\n\n[r]: u', '[$$x$$][r]\n\n[r]: u'],                                  // a full reference: its text is text
    ['a\\\n\\[x\\]', 'a\\\n$$\nx\n$$'],                                               // a hard break, then a formula on its own line
    ['1. a\n\n    \\(x\\)', '1. a\n\n    $$x$$'],
    ['text\n    \\(x\\)', 'text\n    $$x$$'],                                         // a paragraph's next line, not code
    ['$$\na\n\nb\n$$\n\n\\(z\\)', '$$\na\n\nb\n$$\n\n$$z$$'],                               // a fence with a blank line, as written
    ['$$\na\n\n> \\(z\\)', '$$\na\n\n> $$z$$'],                                          // still streaming
    ['> $$\n> a\n>\n> b\n> $$\n\n\\(z\\)', '> $$\n> a\n>\n> b\n> $$\n\n$$z$$'],
  ])('what only looks literal is still read: %j', (from, to) => { expect(rewrite(from)).toBe(to); });

  it.each([
    ['\\[x\\]', '$$\nx\n$$'],
    ['\\[ x \\]', '$$\nx\n$$'],
    ['\\[\nx\n\\]', '$$\nx\n$$'],
    ['\\[ a\nb \\]', '$$\na\nb\n$$'],
    ['\\[\na\n+ b\n\\]', '$$\na\n+ b\n$$'],                                         // not a list in the middle of a formula
    ['\\[ a \\\\[2pt] b \\]', '$$\na \\\\[2pt] b\n$$'],                                // TeX's own line break with a size
    ['text\n\\[x\\]\nmore', 'text\n$$\nx\n$$\nmore'],
    ['\\[a\\]\n\\[b\\]', '$$\na\n$$\n$$\nb\n$$'],
    ['> \\[x\\]', '> $$\n> x\n> $$'],
    ['> \\[\n> x\n> \\]', '> $$\n> x\n> $$'],
    ['>\\[x\\]', '>$$\n>x\n>$$'],
    ['- \\[x\\]', '- $$\n  x\n  $$'],
    ['1. \\[x\\]\n2. b', '1. $$\n   x\n   $$\n2. b'],
    ['> - \\[x\\]', '> - $$\n>   x\n>   $$'],
    ['1. a\n   \\[\n   x\n   \\]\n2. b', '1. a\n   $$\n   x\n   $$\n2. b'],
    ['1. a\n\n    \\[x\\]', '1. a\n\n    $$\n    x\n    $$'],
    ['\\[x\\]\r\nmore', '$$\nx\n$$\r\nmore'],
    [`\\[${'x'.repeat(4096)}\\]`, `$$\n${'x'.repeat(4096)}\n$$`],
    ['1. a\n\n    \\[x\\]\n    text', '1. a\n\n    $$\n    x\n    $$\n    text'],        // its next line is only as deep as the block
  ])('\\[ that fills its lines is display, in its container: %j', (from, to) => { expect(rewrite(from)).toBe(to); });

  it.each([
    'see \\[1\\] and \\[2\\] here',
    '\\[a\\] and \\[b\\]',
    '\\[a\\].',
    'x \\[a\\]',
    '# \\[x\\]',
    '| \\[x\\] | b |\n|---|---|\n| c | d |',
    '\\[a\n\nb\\]',
    '\\[ half streamed',
    '\\[\\[\\]',
    '\\[a\\] b\\]',                                     // its first closer doesn't end the line
    `\\[${'x'.repeat(4097)}\\]`,
    '\\[\n```\nx\n```\n\\]',                               // a code block stays one
    'text\n2. \\[x\\]',                                    // that 2. can't start a list here, so it's not a marker
    '1. \\[\nx\n\\]',                                     // its lines fall out of the item, and a fence there would swallow the reply
    '> \\[ a\nb \\]',
    '\\[x\\]\n    text',                                 // a block here would turn that line into code
    '\\[x\\]\n\ttext',
  ])('elsewhere \\[ stays an escaped bracket: %j', (text) => { expect(rewrite(text)).toBe(text); });

  it.each([
    ['$$x$$', '$$\nx\n$$'],
    ['  $$x$$  ', '  $$\n  x\n  $$'],
    ['> $$x$$', '> $$\n> x\n> $$'],
    ['- $$x$$', '- $$\n  x\n  $$'],
    ['$$\\href{https://e.org}{x}$$', '$$\n\\href{https://e.org}{x}\n$$'],                  // a URL doesn't take the closing $$
    ['$$a + b\n+ c$$', '$$\na + b\n+ c\n$$'],
    [`$$${'x'.repeat(4096)}$$`, `$$\n${'x'.repeat(4096)}\n$$`],
    ['$$ a\nb $$', '$$\na\nb\n$$'],
    ['$$ a\nb\n$$', '$$\na\nb\n$$'],
    ['$$\na$$', '$$\na\n$$'],
    ['> $$ a\n> b $$', '> $$\n> a\n> b\n> $$'],
    ['- $$ a\n  b $$', '- $$\n  a\n  b\n  $$'],
    ['- $$\n  a$$', '- $$\n  a\n  $$'],
    ['text\n$$ a\nb $$', 'text\n$$\na\nb\n$$'],
  ])('$$ with text on its line is a block when a later line closes it: %j', (from, to) => { expect(rewrite(from)).toBe(to); });

  it.each([
    ['$$ a sentence', '\\$\\$ a sentence'],
    ['$$ a sentence\n\nThe next.', '\\$\\$ a sentence\n\nThe next.'],
    ['$$ a\n\nb $$', '\\$\\$ a\n\nb \\$\\$'],
    ['$$ half\nstreamed', '\\$\\$ half\nstreamed'],
    ['- $$ a', '- \\$\\$ a'],
    ['> $$ a', '> \\$\\$ a'],
    ['x $$ y\n$$ z', 'x \\$\\$ y\n\\$\\$ z'],
    ['- $$ a\nb $$', '- \\$\\$ a\nb \\$\\$'],                                                // its next line is out of the item
    ['$$ `\\(c\\)` \\(x\\)', '\\$\\$ `\\(c\\)` $$x$$'],                             // and an old stray $$ can't pair with a new one
    ['cost $$ and \\(x\\)', 'cost \\$\\$ and $$x$$'],
    ['a $$ b\n\n\\(x\\)\n\nc $$ d', 'a \\$\\$ b\n\n$$x$$\n\nc \\$\\$ d'],                 // no formula across a blank line
  ])('$$ with text on its line and no closer is escaped: %j', (from, to) => { expect(rewrite(from)).toBe(to); });

  it.each([
    'a $$x$$ b',
    '$$x$$ and more',
    '$$a$$ and $$b$$',
    'text\n2. $$x$$',
    '$$\nx\n$$',
    '$$\nx\n\ny\n$$',
    '$$\nhalf streamed',
    '$$ a $ b $$',
    '$$x$$\n    text',                                    // a block here would turn that line into code, so it stays in the line
    `$$${'x'.repeat(4097)}$$`,                             // over the cap: stays in the line, where Formula shows it as text
    '\\(a $$ b\\)',                                        // a $$ inside would pair with the one this adds
  ])('other $$ stays as written: %j', (text) => { expect(rewrite(text)).toBe(text); });

  it('what a rejected block holds is still read', () => {
    expect(rewrite('1. \\[\n\\(y\\)\n\\]')).toBe('1. \\[\n$$y$$\n\\]');
    expect(rewrite('- $$ a\n\\(y\\)\nb $$')).toBe('- \\$\\$ a\n$$y$$\nb \\$\\$');
  });

  it('asks the parser only when there is something to rewrite: most replies have nothing', () => {
    const spy = vi.fn(parse);
    for (const text of ['plain', 'It costs $5 and $10', 'a $$x$$ b', '$$\nx\n$$', '> $$\n> x\n> $$', 'see \\[1\\] here', '\\[\\[\\[\\[', '\\(\\(\\(', 'still streaming $$a_{12', 'one $$x$$ then $$y']) expect(texDelimiters(text, spy)).toBe(text);
    expect(spy).not.toHaveBeenCalled();
    for (const text of ['\\(x\\)', '\\[x\\]', '$$x$$', '$$ a', '$$\nx$$']) texDelimiters(text, spy);
    expect(spy).toHaveBeenCalledTimes(5);
  });

  // Reading the source of each: unfixed, the first takes many seconds. The limit is wide because these machines are loaded.
  it.each([
    ['\\[ with no closer', '\\['.repeat(128_000)],
    ['\\( with no closer', '\\('.repeat(128_000)],
    ['\\[ then text, with no closer', `${'\\['.repeat(60_000)}${'x'.repeat(16_000)}`],
    ['\\( then text, with no closer', `${'\\('.repeat(60_000)}${'x'.repeat(16_000)}`],
    ['lines of \\[ with no closer', '\\[ a\n'.repeat(50_000)],
    ['lines of $$ with no closer', '$$ a\n'.repeat(50_000)],
    ['$$ on one line', '$$ '.repeat(85_000)],
    ['$ on one line', '$'.repeat(256_000)],
    ['spaces after $$', `$$${' '.repeat(256_000)}`],
    ['backslashes', '\\'.repeat(256_000)],
    ['line ends', '\n'.repeat(256_000)],
    ['a long formula', `$$${'x'.repeat(256_000)}$$`],
    ['one opener far from its closer', `\\[${'x '.repeat(128_000)}\\]`],
  ])('stays linear on 256 kB of %s', (_, text) => {
    const started = Date.now();
    texDelimiters(text, () => ({ type: 'root', children: [] }));
    expect(Date.now() - started).toBeLessThan(1500);
  });

  // Differential, over generated replies: Markdown's literal text and link targets come through unchanged, and no fence keeps text
  // as its meta. Literal text may only go into a formula that opened before it, as in $$ `a` $$.
  it('leaves code and link targets alone, and no text in a meta, across generated replies', () => {
    let seed = 736;
    const next = (count: number) => { seed = (seed * 1664525 + 1013904223) >>> 0; return Math.floor((seed / 2 ** 32) * count); };
    const pick = (from: string[]) => from[next(from.length)];
    const inlines = ['W \\(x\\) W', 'W $$y$$ W', '**W** \\(a_1\\)', '`\\(c\\)` W', '`$$` W', '[W](https://e.org/\\(1\\))', '[W](u "t\\(2\\)")', 'https://e.org/\\(3\\) W', '![W](v\\(4\\))', 'see \\[1\\] and \\[2\\] W', 'W', '$$ W sentence', '<b title="\\(5\\)"> W', '\\\\(esc\\\\) W'];
    const display = ['\\[x\\]', '\\[ x + y \\]', '\\[\nx\n\\]', '$$x$$', '$$\nx\n$$', '$$ a +\nb $$', '$$\na\n\nb\n$$', '\\[ x', '$$ half'];
    const code = ['```\n\\(c\\)\n\\[d\\]\n$$\n```', '~~~tex\n\\[e\\]\n~~~', '````\n```\n\\(f\\)\n```\n````', '    \\(g\\) code\n    \\[h\\]'];
    const leaf = () => { const kind = next(10); return pick(kind < 4 ? inlines : kind < 8 ? display : code); };
    const prefix = (block: string, first: string, rest: string) => block.split('\n').map((line, i) => (i ? rest : first) + line).join('\n');
    const block = () => {
      const kind = next(20);
      if (kind < 6) return leaf();
      if (kind < 9) return prefix(leaf(), '> ', '> ');
      if (kind < 13) return Array.from({ length: 1 + next(3) }, (_, i) => prefix(`W\n${leaf()}`, `${i + 1}. `, '   ')).join(next(2) ? '\n' : '\n\n');
      if (kind < 15) return prefix(leaf(), '- ', '  ');
      if (kind < 17) return `1. W\n\n${prefix(leaf(), '    ', '    ')}`;
      if (kind < 19) return `- W\n${prefix(leaf(), '  ', '  ')}`;
      return '| \\(a\\) | \\[b\\] |\n|---|---|\n| `\\(c\\)` | $$d$$ |';
    };
    type Node = { type: string; value?: string; url?: string; meta?: string | null; children?: Node[] };
    const read = (doc: string) => {
      const out = { literal: [] as string[], math: [] as string[], metas: 0 };
      const walk = (node: Node) => {
        if (['code', 'inlineCode', 'html'].includes(node.type)) out.literal.push(node.value!.replace(/##|<</g, '$$$$'));
        if (['link', 'image', 'definition'].includes(node.type)) out.literal.push(node.url!);
        if (node.type === 'math' || node.type === 'inlineMath') out.math.push(node.value!.replaceAll('\\', ''));
        if (node.type === 'math' && node.meta) out.metas += 1;
        node.children?.forEach(walk);
      };
      walk(parse(doc) as Node);
      return out;
    };
    let changed = 0;
    for (let i = 0; i < 400; i += 1) {
      const doc = Array.from({ length: 1 + next(6) }, block).join(next(5) ? '\n\n' : '\n');
      const out = rewrite(doc);
      if (out === doc) continue;
      changed += 1;
      // The reading to keep is Markdown's own, with no formulas: a fence that ran on after a $$ line hid what it swallowed.
      const before = read(doc.replace(/(^|\n)((?:[ >]|\d\. |- )*)\$\$(?= *(?:\n|$))/g, '$1$2##').replaceAll('$$', '<<')).literal;
      const after = read(out);
      expect(after.metas, JSON.stringify(doc)).toBe(0);
      expect(after.literal.filter((value) => !before.includes(value)), JSON.stringify(doc)).toEqual([]);
      expect(before.filter((value) => !after.literal.includes(value) && !after.math.some((tex) => tex.includes(value.replaceAll('\\', '')))), JSON.stringify(doc)).toEqual([]);
    }
    expect(changed).toBeGreaterThan(200);
  }, 120_000);
});

describe('what the rewrite does to a reply', () => {
  it('a formula in a numbered list stays in the list, and the numbers keep counting', async () => {
    await katexLoaded();
    const c = show('1. First:\n   \\[\n   a\n   \\]\n2. Second:\n   \\[ b \\]\n3. Third\n');
    expect(c.querySelectorAll('ol')).toHaveLength(1);
    expect(c.querySelectorAll('ol > li')).toHaveLength(3);
    expect(c.querySelectorAll('ol > li .katex-display')).toHaveLength(2);
  });

  it('a list that really is split keeps counting from where it was', () => {
    const c = show('1. a\n2. b\n\ntext\n\n3. c\n');
    expect(Array.from(c.querySelectorAll('ol')).map((ol) => ol.getAttribute('start'))).toEqual([null, '3']);
  });

  it('a formula in a quote has its own text, with no > in it', async () => {
    await katexLoaded();
    const c = show('> \\[ a\n> b \\]\n');
    expect(c.querySelectorAll('blockquote .katex-display')).toHaveLength(1);
    expect(c.querySelector('annotation')!.textContent).toBe('a\nb');
  });

  it('a table keeps its rows, and a heading stays one heading', () => {
    const table = show('| \\[x\\] | b |\n|---|---|\n| c | d |\n');
    expect(table.querySelectorAll('tr')).toHaveLength(2);
    expect(table.querySelector('th')!.textContent).toBe('[x]');
    cleanup();
    const heading = show('# Title \\[x\\] end\n');
    expect(heading.querySelector('h1')!.textContent).toBe('Title [x] end');
    expect(heading.children[0].children).toHaveLength(1);
  });

  it('escaped brackets, as in a converted page, stay brackets', () => {
    const c = show('See \\[1\\] and \\[2\\].\n');
    expect(c.querySelector('.md-math')).toBeNull();
    expect(c.textContent).toBe('See [1] and [2].');
  });

  it('indented code shows and copies what was written', () => {
    const c = show('Run:\n\n    echo \\(x\\) \\[y\\]\n');
    expect(c.querySelector('pre')!.textContent).toBe('echo \\(x\\) \\[y\\]\n');
  });

  it('a link goes where it said', () => {
    const c = show('[a](https://e.org/f\\(1\\)) and https://e.org/g\\(2\\)\n');
    expect(Array.from(c.querySelectorAll('a')).map((a) => a.getAttribute('href'))).toEqual(['https://e.org/f(1)', 'https://e.org/g%5C(2%5C)']);
  });

  it('a sentence that starts with $$ is read, and the next paragraph stays a paragraph', () => {
    const c = show('$$ a sentence about cost\n\nThe next paragraph has **bold**.\n');
    expect(c.querySelector('.md-math')).toBeNull();
    expect(c.querySelectorAll('p')).toHaveLength(2);
    expect(c.querySelector('p')!.textContent).toBe('$$ a sentence about cost');
    expect(c.querySelector('strong')!.textContent).toBe('bold');
  });

  it('a formula on several lines shows all of it', async () => {
    await katexLoaded();
    const c = show('$$ a +\nb +\nc $$\n');
    expect(c.querySelectorAll('.katex-display')).toHaveLength(1);
    expect(c.querySelector('annotation')!.textContent).toBe('a +\nb +\nc');
  });

  it('a formula still streaming at a line\'s start shows its source, not nothing', () => {
    const c = show('$$ \\frac{1}{2} +');
    expect(c.textContent).toBe('$$ \\frac{1}{2} +');
  });

  it('$$x$$ alone on a line is display, as \\[x\\] is, and in a sentence it stays inline', async () => {
    await katexLoaded();
    const c = show('$$x$$\n\nand $$y$$ here\n');
    expect(c.querySelectorAll('.katex-display')).toHaveLength(1);
    expect(typeset(c)).toHaveLength(2);
  });
});

describe('lists', () => {
  it('an ordered item has its number and no dot; a bullet is drawn by the stylesheet', () => {
    const c = show(REPLY);
    const ol = c.querySelector('ol')!;
    expect(ol.querySelectorAll('li > span')).toHaveLength(0);
    expect(ol.classList.contains('md-ol')).toBe(true);
    expect(c.querySelector('ul')!.classList.contains('md-ul')).toBe(true);
    expect(sheet()).toMatch(/\.md-ul > li::before\s*\{[^}]*background: var\(--color-muted-foreground\)/);
  });

  it('one level down the dot is hollow', () => {
    expect(sheet()).toMatch(/\.md-ul \.md-ul > li::before\s*\{[^}]*background: transparent;[^}]*border: 1px solid var\(--color-muted-foreground\)/);
  });

  it('nests', () => {
    const c = show(REPLY);
    expect(c.querySelector('ul li ul li')!.textContent).toBe('Keep the newest');
  });
});

describe('task checkboxes', () => {
  it('are read-only, say whether they are done, and mark their list item', () => {
    const c = show(REPLY);
    const boxes = Array.from(c.querySelectorAll<HTMLInputElement>('input[type=checkbox]'));
    expect(boxes.map((b) => b.checked)).toEqual([true, false]);
    expect(boxes.every((b) => b.disabled && b.classList.contains('md-check'))).toBe(true);
    expect(boxes[0].closest('li')!.classList.contains('task-list-item')).toBe(true);
    expect(boxes[0].closest('li')!.textContent).toBe('Compared');                // no lone space for the strike to cross
    expect(c.querySelector('ul.contains-task-list')).not.toBeNull();
  });

  it('the stylesheet fills a done one with a tick and strikes its text', () => {
    expect(sheet()).toMatch(/\.md-check:checked\s*\{[^}]*background: var\(--color-foreground\)/);
    expect(sheet()).toMatch(/\.md-check:checked::after\s*\{[^}]*content: '✓'/);
    expect(sheet()).toMatch(/\.task-list-item:has\(> \.md-check:checked\)\s*\{[^}]*line-through/);
  });

  it('React has no complaint about a box with no handler', () => {
    const complaint = vi.spyOn(console, 'error');
    show(REPLY);
    expect(complaint).not.toHaveBeenCalled();
  });
});

describe('tables', () => {
  it('keep the alignment the Markdown asked for, in the header and the cells', () => {
    const c = show(REPLY);
    expect(Array.from(c.querySelectorAll('th')).map((h) => (h as HTMLElement).style.textAlign)).toEqual(['left', 'center', 'right']);
    expect(Array.from(c.querySelectorAll('td')).map((d) => (d as HTMLElement).style.textAlign)).toEqual(['left', 'center', 'right']);
  });

  it('a plain bold header, not upper-cased, and they can still scroll sideways', () => {
    const c = show(REPLY);
    const th = c.querySelector('th') as HTMLElement;
    expect(th.style.textTransform).not.toBe('uppercase');
    expect(th.style.color).not.toContain('--color-primary');
    expect((c.querySelector('table')!.parentElement as HTMLElement).style.overflowX).toBe('auto');
    expect((c.querySelector('table') as HTMLElement).style.minWidth).toBe('');
  });
});

/**
 * FMT1 PR 2 (0.1.64): a reply's structure catches up with the iPhone mock. One fixture reply with every element, then what
 * each must do:
 * - a formula is typeset by KaTeX into nodes it builds itself, never from an HTML string, and a single `$` is never math;
 * - a broken or half-streamed formula, and one over the size cap, show their source as text, not a red error;
 * - a formula that hasn't changed is not typeset again while a reply streams;
 * - lists: a number or a dot, never both, and a hollow dot one level down;
 * - task checkboxes are read-only; tables keep the alignment the Markdown asked for.
 */
import { cleanup, render, waitFor } from '@testing-library/react';
import katex from 'katex';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
  Trans: ({ children }: { children?: unknown }) => children,
}));

import Markdown from '../components/Markdown';
import { buildStandaloneHtml } from '../components/MessageBody';
import { texDelimiters } from '../lib/texDelimiters';

const here = dirname(fileURLToPath(import.meta.url));
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
});

describe('texDelimiters', () => {
  it.each([
    ['\\(x\\)', '$$x$$'],
    ['\\[x\\]', '\n$$\nx\n$$\n'],
    ['a \\(x\\) b \\(y\\) c', 'a $$x$$ b $$y$$ c'],
    ['literal \\\\(x\\\\) stays', 'literal \\\\(x\\\\) stays'],
    ['an unclosed \\(x stays', 'an unclosed \\(x stays'],
    ['`\\(x\\)`', '`\\(x\\)`'],
    ['``\\(x\\)``', '``\\(x\\)``'],
    ['```\n\\[x\\]\n```', '```\n\\[x\\]\n```'],
    ['~~~tex\n\\(x\\)\n~~~\n\\(y\\)', '~~~tex\n\\(x\\)\n~~~\n$$y$$'],
    ['  ```\n  \\(x\\)\n  ```', '  ```\n  \\(x\\)\n  ```'],
    ['```\nan unclosed fence \\(x\\)', '```\nan unclosed fence \\(x\\)'],
    ['\\(two\nlines\\)', '\\(two\nlines\\)'],
  ])('%j', (from, to) => { expect(texDelimiters(from)).toBe(to); });
});

describe('lists', () => {
  it('an ordered item has its number and no dot; a bullet is drawn by the stylesheet', () => {
    const c = show(REPLY);
    const ol = c.querySelector('ol')!;
    expect(ol.querySelectorAll('li > span')).toHaveLength(0);
    expect(ol.classList.contains('md-ol')).toBe(true);
    expect(c.querySelector('ul')!.classList.contains('md-ul')).toBe(true);
    const sheet = readFileSync(resolve(here, '../index.css'), 'utf8');
    expect(sheet).toMatch(/\.md-ul > li::before/);
    expect(sheet).toMatch(/\.md-ul \.md-ul > li::before/);        // hollow, one level down
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

  it('the stylesheet fills a done one and strikes its text', () => {
    const sheet = readFileSync(resolve(here, '../index.css'), 'utf8');
    expect(sheet).toMatch(/\.md-check:checked/);
    expect(sheet).toMatch(/\.task-list-item:has\(> \.md-check:checked\)\s*\{[^}]*line-through/);
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

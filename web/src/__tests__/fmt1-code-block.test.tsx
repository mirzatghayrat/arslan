/**
 * FMT1 PR 1 (0.1.64): the Mac's code block catches up with the iPhone mock.
 * - the header names the language as written (lower case) and has one copy button;
 * - code is highlighted into token spans, built as React text nodes (never as HTML);
 * - copy puts the raw code on the clipboard, never the highlighted markup;
 * - a language name the model invents can never reach Prism's own helper functions;
 * - inline code is a filled chip, not orange text in a bordered box;
 * - the colours are tokens defined for light and dark, not literals in the component.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
  Trans: ({ children }: { children?: unknown }) => children,
}));

import Markdown from '../components/Markdown';

const here = dirname(fileURLToPath(import.meta.url));
const writeText = vi.fn(() => Promise.resolve());
beforeEach(() => { Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true }); });
afterEach(() => { cleanup(); writeText.mockClear(); });

const BASH = 'shasum -a 256 ~/Downloads/* | sort\n# same hash = same file\n';

function fence(lang: string, code: string) {
  const { container } = render(<Markdown>{`Before\n\n\`\`\`${lang}\n${code}\`\`\`\n`}</Markdown>);
  return container;
}
const tokens = (root: ParentNode, kind?: string) =>
  Array.from(root.querySelectorAll(kind ? `.token.${kind}` : '.token'));

describe('header', () => {
  it('shows the language as the model wrote it, not upper-cased', () => {
    const c = fence('bash', BASH);
    const label = c.querySelector('[data-testid=code-lang]') as HTMLElement;
    expect(label.textContent).toBe('bash');
    expect(label.style.textTransform).not.toBe('uppercase');
  });

  it('a fence with no language says "ui.code"', () => {
    const c = fence('', 'plain words\n');
    expect((c.querySelector('[data-testid=code-lang]') as HTMLElement).textContent).toBe('ui.code');
  });

  it('has exactly one copy button, inside the header, not floating over the code', () => {
    const c = fence('bash', BASH);
    const buttons = c.querySelectorAll('button');
    expect(buttons).toHaveLength(1);
    expect(buttons[0].style.position).not.toBe('absolute');
    expect(c.querySelector('[data-testid=code-header]')!.contains(buttons[0])).toBe(true);
  });
});

describe('highlighting', () => {
  it('marks comments, numbers, commands and flags in a bash block, and loses no character', () => {
    const c = fence('bash', BASH);
    const pre = c.querySelector('pre') as HTMLPreElement;     // the only <pre> holds the code
    expect(pre.textContent).toBe(BASH);
    expect(tokens(pre, 'comment').map((t) => t.textContent)).toEqual(['# same hash = same file']);
    expect(tokens(pre, 'number').map((t) => t.textContent)).toEqual(['256']);
    expect(tokens(pre, 'function').map((t) => t.textContent)).toContain('sort');
    expect(tokens(pre, 'parameter').map((t) => t.textContent)).toEqual(['-a']);
  });

  it.each([
    ['sh', 'echo hi # c\n'],
    ['shell', 'echo hi # c\n'],
    ['zsh', 'echo hi # c\n'],
    ['jsonc', '{"a": 1}\n'],
    ['python', 'def f(x):\n    return x + 1  # c\n'],
    ['py', 'def f(x):\n    return x + 1\n'],
    ['javascript', 'const a = 1; // c\n'],
    ['js', 'const a = 1;\n'],
    ['typescript', 'const a: number = 1;\n'],
    ['ts', 'const a: number = 1;\n'],
    ['tsx', 'const a = <b>{1}</b>;\n'],
    ['json', '{"a": [1, true, null]}\n'],
    ['yaml', 'a: 1\nb: "x" # c\n'],
    ['yml', 'a: 1\n'],
    ['toml', 'a = 1\n'],
    ['css', 'a { color: red; }\n'],
    ['html', '<p class="x">hi</p>\n'],
    ['xml', '<a b="c"/>\n'],
    ['sql', 'SELECT 1 FROM t;\n'],
    ['swift', 'let a = 1\n'],
    ['rust', 'fn main() { let a = 1; }\n'],
    ['go', 'func main() { a := 1 }\n'],
    ['java', 'class A { int a = 1; }\n'],
    ['c', 'int a = 1;\n'],
    ['cpp', 'int a = 1;\n'],
    ['diff', '+ added\n- removed\n'],
    ['BASH', 'echo hi\n'],
  ])('%s is highlighted', (lang, code) => {
    const c = fence(lang, code);
    const pre = c.querySelector('pre') as HTMLPreElement;
    expect(tokens(pre).length).toBeGreaterThan(0);
    expect(pre.textContent).toBe(code);
  });

  it('colours the added and removed lines of a diff apart', () => {
    const c = fence('diff', '+ added\n- removed\n');
    expect(tokens(c, 'inserted-sign')).toHaveLength(1);
    expect(tokens(c, 'deleted-sign')).toHaveLength(1);
    expect(tokens(c, 'inserted-sign')[0].classList.contains('deleted')).toBe(false);
    expect(tokens(c, 'inserted').length).toBeGreaterThan(0);          // the alias class the stylesheet colours by
    expect(tokens(c, 'deleted').length).toBeGreaterThan(0);
  });

  it.each(['', 'text', 'txt', 'plaintext', 'markdown', 'md', 'klingon'])(
    'a "%s" fence stays plain text', (lang) => {
      const c = fence(lang, 'echo "hi" # not code\n');
      expect(tokens(c)).toHaveLength(0);
      expect((c.querySelector('pre') as HTMLPreElement).textContent).toBe('echo "hi" # not code\n');
    });

  it.each(['extend', 'insertBefore', 'DFS', 'constructor', '__proto__', 'toString', 'hasOwnProperty', 'valueOf', 'plain'])(
    'the made-up language "%s" renders its text and does not throw', (lang) => {
      const c = fence(lang, 'x = 1\n');
      expect((c.querySelector('pre') as HTMLPreElement).textContent).toBe('x = 1\n');
    });

  it('code that looks like HTML stays text: no element is created from it', () => {
    const c = fence('html', '<img src=x onerror="alert(1)"><script>alert(2)</script>\n');
    expect(c.querySelector('img')).toBeNull();
    expect(c.querySelector('script')).toBeNull();
    expect((c.querySelector('pre') as HTMLPreElement).textContent)
      .toBe('<img src=x onerror="alert(1)"><script>alert(2)</script>\n');
  });

  it('Prism is told not to highlight the page by itself (it would rewrite what React renders)', () => {
    expect((window as unknown as { Prism: { manual?: boolean } }).Prism.manual).toBe(true);
  });

  it('an unfinished fence (a reply still streaming) renders what it has', () => {
    const { container, rerender } = render(<Markdown>{'```bash\necho "unfini'}</Markdown>);
    expect((container.querySelector('pre') as HTMLPreElement).textContent).toContain('echo "unfini');
    rerender(<Markdown>{'```bash\necho "unfinished" # done\n```\n'}</Markdown>);
    expect(tokens(container, 'comment').map((t) => t.textContent)).toEqual(['# done']);
  });

  it('keeps the prose wrap of text fences and the horizontal scroll of code fences', () => {
    const prose = fence('text', 'a long line\n').querySelector('pre') as HTMLPreElement;
    expect(prose.style.whiteSpace).toBe('pre-wrap');
    cleanup();
    const code = fence('bash', 'echo hi\n').querySelector('pre') as HTMLPreElement;
    expect(code.style.whiteSpace).toBe('pre');
  });
});

describe('copy', () => {
  it('puts the raw code on the clipboard, not the highlighted markup', async () => {
    fence('bash', BASH);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText).toHaveBeenCalledWith(BASH);
  });

  it('the label turns to "ui.copied" after the click', async () => {
    fence('bash', BASH);
    expect(screen.getByRole('button').textContent).toBe('ui.copy');
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(screen.getByRole('button').textContent).toBe('ui.copied'));
  });
});

describe('inline code', () => {
  it('is a filled chip in the surrounding text colour, with no border', () => {
    const { container } = render(<Markdown>{'I compared them with `shasum` first.'}</Markdown>);
    const code = container.querySelector('p code') as HTMLElement;
    expect(code.textContent).toBe('shasum');
    const style = code.getAttribute('style') ?? '';
    expect(style).toContain('background');
    expect(style).toContain('--color-fill');
    expect(style).not.toMatch(/(^|;)\s*border\s*:/);                  // border-radius is fine, a border is not
    expect(style).not.toContain('--color-primary');
  });
});

describe('colour tokens', () => {
  const css = readFileSync(resolve(here, '../theme/tokens.css'), 'utf8');
  const kinds = ['comment', 'keyword', 'number', 'string', 'inserted', 'deleted'];
  /** Everything declared under a bare `selector {` rule, joined (the file has several `:root` and `.dark` rules). */
  const declared = (selector: string) =>
    Array.from(css.matchAll(new RegExp(`^${selector.replace('.', '\\.')} \\{([^}]*)\\}`, 'gm')), (m) => m[1]).join('\n');

  it.each(kinds)('--code-%s is defined for light and for dark', (kind) => {
    expect(declared(':root')).toContain(`--code-${kind}:`);
    expect(declared('.dark')).toContain(`--code-${kind}:`);
  });

  it('every token kind the stylesheet colours has a token', () => {
    const sheet = readFileSync(resolve(here, '../index.css'), 'utf8');
    const used = new Set(Array.from(sheet.matchAll(/var\(--code-([a-z-]+)\)/g), (m) => m[1]));
    expect(Array.from(used).sort()).toEqual([...kinds].sort());
  });

  it('the component carries no colour literal for tokens', () => {
    const src = readFileSync(resolve(here, '../components/HighlightedCode.tsx'), 'utf8');
    expect(src).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(/);
  });
});

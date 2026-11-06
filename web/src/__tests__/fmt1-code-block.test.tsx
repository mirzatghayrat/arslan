/**
 * FMT1 PR 1 (0.1.64): the Mac's code block catches up with the iPhone mock.
 * - the header names the language as written (lower case) and has one copy button;
 * - code is highlighted into token spans, built as React text nodes (never as HTML);
 * - Prism runs in a worker that is terminated when it takes too long, so no fence can freeze the window;
 * - copy puts the raw code on the clipboard, never the highlighted markup;
 * - a language name the model invents can never reach Prism's own helper functions;
 * - inline code is a filled chip, not orange text in a bordered box;
 * - the colours are tokens defined for light and dark, not literals in the component.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
  Trans: ({ children }: { children?: unknown }) => children,
}));

import { tokenize, type Tokens } from '../lib/highlightTokens';
import Markdown from '../components/Markdown';
import HighlightedCode from '../components/HighlightedCode';
import { answerFor, ask } from '../lib/highlightClient';
import Prism from 'prismjs';                                            // after highlightTokens: it loads Prism with auto-highlight off
import { buildStandaloneHtml } from '../components/MessageBody';

const here = dirname(fileURLToPath(import.meta.url));
const writeText = vi.fn(() => Promise.resolve());
beforeEach(() => { Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true }); });
afterEach(() => { cleanup(); writeText.mockClear(); });

/**
 * Unlike the one in test/setup.ts, this Worker highlights: the real tokenizer, answering with a clone as a real one would,
 * at once, or when `answerHeld` says so while `hold` is on (a slow grammar). A real worker ran it too: see the PR.
 */
const workers: FakeWorker[] = [];
let hold = false;
class FakeWorker {
  onmessage: ((e: { data: Tokens }) => void) | null = null;
  onerror: (() => void) | null = null;
  asked: string[] = [];
  held: { code: string; lang: string } | null = null;
  terminated = false;
  constructor() { workers.push(this); }
  postMessage(m: { code: string; lang: string }) {
    this.asked.push(m.code);
    if (hold) this.held = m; else this.send(m);
  }
  send(m: { code: string; lang: string }) { this.onmessage!({ data: structuredClone(tokenize(m.code, m.lang)) }); }
  terminate() { this.terminated = true; this.held = null; }
}
vi.stubGlobal('Worker', FakeWorker);
const current = () => workers[workers.length - 1];
function answerHeld() {
  const m = current().held!;
  current().held = null;
  act(() => current().send(m));
}
afterEach(() => { hold = false; while (workers.length && current().held) answerHeld(); });

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
    ['rs', 'fn main() { let a = 1; }\n'],
    ['golang', 'func main() { a := 1 }\n'],
    ['c++', 'int a = 1;\n'],
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

  it('Prism is told not to touch a page, and not to answer a worker\'s messages itself', () => {
    const settings = (window as unknown as { Prism: { manual?: boolean; disableWorkerMessageHandler?: boolean } }).Prism;
    expect(settings.manual).toBe(true);
    expect(settings.disableWorkerMessageHandler).toBe(true);
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


describe('review fixes', () => {
  it('the code element keeps the md-code class the stylesheet colours by', () => {
    expect(fence('bash', BASH).querySelector('pre')!.classList.contains('md-code')).toBe(true);
  });

  it('the label shows the language exactly as written, capitals included', () => {
    expect(fence('Python', 'x = 1\n').querySelector('[data-testid=code-lang]')!.textContent).toBe('Python');
  });

  it('a long info string is clipped in the label and cannot push Copy out of the header', () => {
    const lang = `${'very/long/path/'.repeat(10)}file.py`;
    const c = fence(lang, 'x = 1\n');
    const label = c.querySelector('[data-testid=code-lang]') as HTMLElement;
    expect(label.textContent).toBe(lang);
    expect(label.getAttribute('title')).toBe(lang);                   // the whole name is still there on hover
    expect(label.style.overflow).toBe('hidden');
    expect(label.style.textOverflow).toBe('ellipsis');
    expect(label.style.minWidth).toBe('0px');
    expect(c.querySelector('button')!.style.flexShrink).toBe('0');
  });

  it('JSX text inside a tag is not coloured as code (Prism needs its after-tokenize hook)', () => {
    const c = fence('tsx', 'const a = <b>return if</b>;\n');
    expect(tokens(c, 'keyword').map((t) => t.textContent)).toEqual(['const']);
  });

  it('the exported HTML defines the inline-code fill', () => {
    expect(buildStandaloneHtml('<p>x</p>', 't')).toContain('--color-fill:');
  });

  it('highlights without innerHTML', () => {
    const src = readFileSync(resolve(here, '../components/HighlightedCode.tsx'), 'utf8');
    expect(src).not.toMatch(/dangerouslySetInnerHTML|innerHTML/);
  });

  it('the stylesheet colours tokens only under .md-code, and resets Tailwind\'s .table', () => {
    const sheet = readFileSync(resolve(here, '../index.css'), 'utf8');
    for (const kind of ['comment', 'keyword', 'number', 'string', 'inserted', 'deleted']) {
      const rule = sheet.match(new RegExp(`([^{}]+)\\{\\s*color: var\\(--code-${kind}\\);\\s*\\}`));
      expect(rule, kind).not.toBeNull();
      for (const selector of rule![1].split(',').map((x) => x.trim())) expect(selector).toMatch(/^\.md-code \.token\.[a-z-]+$/);
    }
    // Prism's token type `table` (a TOML [section]) would otherwise get Tailwind's `.table { display: table }`.
    expect(sheet).toMatch(/\.md-code \.token\s*\{[^}]*display:\s*inline/);
  });

  it('a TOML section header is a token that needs that reset', () => {
    const c = fence('toml', '[package]\nname = "x"\n');
    expect(tokens(c, 'table').map((t) => t.textContent)).toEqual(['package']);
  });
});

describe('Prism runs in a worker, and a slow one is terminated', () => {
  it('the window does not load Prism: only its types', () => {
    for (const file of ['../components/HighlightedCode.tsx', '../lib/highlightClient.ts', '../components/Markdown.tsx']) {
      const src = readFileSync(resolve(here, file), 'utf8');
      expect(src, file).not.toMatch(/^import (?!type )[^\n]*(prismjs|highlightTokens)/m);
      expect(src, file).not.toMatch(/^import '[^']*(prismjs|prismManual)/m);
    }
  });

  it('plain text until the answer is in, then coloured, and no character lost', () => {
    hold = true;
    const c = fence('bash', 'echo waits # one\n');
    expect(tokens(c)).toHaveLength(0);
    expect((c.querySelector('pre') as HTMLPreElement).textContent).toBe('echo waits # one\n');
    answerHeld();
    expect(tokens(c, 'comment').map((t) => t.textContent)).toEqual(['# one']);
    expect((c.querySelector('pre') as HTMLPreElement).textContent).toBe('echo waits # one\n');
  });

  describe('past the budget', () => {
    afterEach(() => { vi.useRealTimers(); });

    it('the worker is terminated at 2 s, the fence stays plain, the next fence gets a new worker', () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      hold = true;
      const slow = fence('bash', 'echo slow # two\n');
      const stuck = current();
      act(() => { vi.advanceTimersByTime(1999); });
      expect(stuck.terminated).toBe(false);
      act(() => { vi.advanceTimersByTime(1); });
      expect(stuck.terminated).toBe(true);
      expect(tokens(slow)).toHaveLength(0);
      expect((slow.querySelector('pre') as HTMLPreElement).textContent).toBe('echo slow # two\n');
      hold = false;
      const after = fence('bash', 'echo after # three\n');
      expect(current()).not.toBe(stuck);
      expect(tokens(after, 'comment').map((t) => t.textContent)).toEqual(['# three']);
    });

    it('the slow fence is not tried again: its remount (a reload of the conversation) stays plain', () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      hold = true;
      fence('bash', 'echo again # four\n');
      act(() => { vi.advanceTimersByTime(2000); });
      cleanup();
      hold = false;
      const before = workers.reduce((n, w) => n + w.asked.length, 0);
      const c = fence('bash', 'echo again # four\n');
      expect(tokens(c)).toHaveLength(0);
      expect(workers.reduce((n, w) => n + w.asked.length, 0)).toBe(before);
    });

    it('an answer in time cancels the budget', () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const w = (fence('bash', 'echo quick # five\n'), current());
      act(() => { vi.advanceTimersByTime(5000); });
      expect(w.terminated).toBe(false);
    });
  });

  it('a worker that errors counts as too slow: plain text, and the next fence gets a new worker', () => {
    hold = true;
    const c = fence('bash', 'echo err # six\n');
    const broken = current();
    hold = false;
    act(() => broken.onerror!());
    expect(broken.terminated).toBe(true);
    expect(tokens(c)).toHaveLength(0);
    expect(tokens(fence('bash', 'echo fine # seven\n')).length).toBeGreaterThan(0);
    expect(current()).not.toBe(broken);
  });

  it('one fence at a time: the second is asked only after the first answered', () => {
    hold = true;
    const c = render(<Markdown>{'```bash\necho first # a1\n```\n\n```bash\necho second # a2\n```\n'}</Markdown>).container;
    expect(current().asked.slice(-1)).toEqual(['echo first # a1\n']);
    answerHeld();
    expect(current().asked.slice(-1)).toEqual(['echo second # a2\n']);
    answerHeld();
    expect(tokens(c, 'comment').map((t) => t.textContent)).toEqual(['# a1', '# a2']);
  });

  it('a fence with no language never wakes the worker', () => {
    const before = workers.reduce((n, w) => n + w.asked.length, 0);
    fence('', 'no language here\n');
    expect(workers.reduce((n, w) => n + w.asked.length, 0)).toBe(before);
  });

  it('a fence well over the old 8 KiB cap is highlighted: only the budget decides', () => {
    const code = '# a comment line of ordinary code\n'.repeat(800);          // 27,200 characters
    expect(tokens(fence('bash', code), 'comment')).toHaveLength(800);
  });

  it('10,000 tokens are shown; one more is plain text, since each is a span the window must render', () => {
    const at = '1,'.repeat(5_000);                                           // a number and a comma each
    expect(tokens(fence('json', at))).toHaveLength(10_000);
    cleanup();
    const over = `${at}1`;
    const c = fence('json', over);
    expect(tokens(c)).toHaveLength(0);
    expect((c.querySelector('pre') as HTMLPreElement).textContent).toContain('1,1,');
  });

  it('a re-render with the same reply asks nothing (typing in the composer re-renders the history)', () => {
    const spy = vi.spyOn(Prism, 'tokenize');
    let bump: () => void = () => {};
    function History({ text }: { text: string }) {
      const [n, setN] = React.useState(0);
      bump = () => setN((v) => v + 1);
      return <div data-n={n}><Markdown>{text}</Markdown></div>;
    }
    const reply = '```bash\necho hi # a\n```\n';
    const { rerender } = render(<History text={reply} />);
    const first = spy.mock.calls.length;
    expect(first).toBeGreaterThan(0);
    act(() => bump());
    act(() => bump());
    expect(spy.mock.calls.length).toBe(first);
    rerender(<History text={`${reply}\nmore\n`} />);                    // the fence's text is the same, so still nothing
    expect(spy.mock.calls.length).toBe(first);
    rerender(<History text={`${reply}\n\`\`\`bash\necho hi # b\n\`\`\`\n`} />);
    expect(spy.mock.calls.length).toBeGreaterThan(first);
    spy.mockRestore();
  });

  it('neither a keystroke nor a stream token re-renders a finished fence', () => {
    const memo = Symbol.for('react.memo');
    expect((Markdown as unknown as { $$typeof: symbol }).$$typeof).toBe(memo);
    expect((HighlightedCode as unknown as { $$typeof: symbol }).$$typeof).toBe(memo);
  });

  it('an answer belongs to the text and the language together', () => {
    const c = render(<HighlightedCode code={'x = 1 # l1\n'} lang="python" />);
    const pythonTokens = c.container.querySelectorAll('.token').length;
    expect(pythonTokens).toBeGreaterThan(0);
    expect(answerFor('x = 1 # l1\n', 'klingon')).toBeUndefined();
    c.rerender(<HighlightedCode code={'x = 1 # l1\n'} lang="klingon" />);    // asked again, for this language
    expect(answerFor('x = 1 # l1\n', 'klingon')).toBeNull();
  });

  it('old answers go first once a million characters are kept, and the newest stays', () => {
    const text = (mark: string) => mark.repeat(600_000);
    ask(text('a'), 'klingon', () => {});
    expect(answerFor(text('a'), 'klingon')).toBeNull();
    ask(text('b'), 'klingon', () => {});
    expect(answerFor(text('a'), 'klingon')).toBeUndefined();
    expect(answerFor(text('b'), 'klingon')).toBeNull();
  });

  it('two identical fences count once, so they do not push out what fits', () => {
    const twice = 'c'.repeat(600_000);
    ask(twice, 'klingon', () => {});
    ask(twice, 'klingon', () => {});
    const next = 'd'.repeat(500_000);
    ask(next, 'klingon', () => {});
    expect(answerFor(next, 'klingon')).toBeNull();
  });

  describe('while a reply streams', () => {
    const md = (code: string) => `\`\`\`bash\n${code}`;

    it('the colours stay up over what is known, and the newest text is there, plain, until the next answer', () => {
      hold = true;
      const { container, rerender } = render(<Markdown>{md('echo stream # s1\n')}</Markdown>);
      answerHeld();
      expect(tokens(container, 'comment').map((t) => t.textContent)).toEqual(['# s1']);
      rerender(<Markdown>{md('echo stream # s1\necho more # s2\n')}</Markdown>);
      expect(tokens(container, 'comment').map((t) => t.textContent)).toEqual(['# s1']);
      expect((container.querySelector('pre') as HTMLPreElement).textContent).toBe('echo stream # s1\necho more # s2\n');
      answerHeld();
      expect(tokens(container, 'comment').map((t) => t.textContent)).toEqual(['# s1', '# s2']);
    });

    it('an answer keeps the spans that are already there: React rebuilds none of them', () => {
      hold = true;
      const { container, rerender } = render(<Markdown>{md('echo nodes # n1\n')}</Markdown>);
      answerHeld();
      const first = container.querySelector('.token');
      rerender(<Markdown>{md('echo nodes # n1\necho on # n2\n')}</Markdown>);
      expect(container.querySelector('.token')).toBe(first);
      answerHeld();
      expect(container.querySelector('.token')).toBe(first);
    });

    it('text that is not a continuation drops the old colours rather than show them over the wrong text', () => {
      hold = true;
      const { container, rerender } = render(<Markdown>{md('echo old # s3\n')}</Markdown>);
      answerHeld();
      rerender(<Markdown>{md('echo different # s4\n')}</Markdown>);
      expect(tokens(container)).toHaveLength(0);
      expect((container.querySelector('pre') as HTMLPreElement).textContent).toBe('echo different # s4\n');
      answerHeld();
    });

    it('only the newest text is asked for: one that is still waiting when the stream moves on never goes out', () => {
      hold = true;
      const { container, rerender } = render(<Markdown>{md('echo s5\n')}</Markdown>);        // goes out, held
      rerender(<Markdown>{md('echo s5\necho s6\n')}</Markdown>);                            // waits
      rerender(<Markdown>{md('echo s5\necho s6\necho s7\n')}</Markdown>);                   // takes its place
      answerHeld();
      expect(current().asked.slice(-2)).toEqual(['echo s5\n', 'echo s5\necho s6\necho s7\n']);
      // The answer that was already out still colours the start of the newer text.
      expect(tokens(container, 'builtin').map((t) => t.textContent)).toEqual(['echo']);
      expect((container.querySelector('pre') as HTMLPreElement).textContent).toBe('echo s5\necho s6\necho s7\n');
      answerHeld();
      expect(tokens(container, 'builtin').map((t) => t.textContent)).toEqual(['echo', 'echo', 'echo']);
    });
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

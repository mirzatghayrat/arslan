/**
 * FMT1 PR 3 (0.1.64): a reply's copy button, and what happens while a reply streams.
 * - The copy icon under a reply copies the whole reply, and every finished reply has one.
 * - While a reply streams, only the block still growing is parsed again, and what shows is what the whole reply would show.
 * - The window takes the text at most once per animation frame. The store keeps every character, at once.
 * - Composing Chinese while a reply streams drops and duplicates nothing. What only a real input method can prove is in the PR.
 */
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

// How often a component using it rendered: a finished reply's body and footer must sit out the chat's renders.
const translated = vi.hoisted(() => ({ count: 0 }));
vi.mock('react-i18next', () => ({
  useTranslation: () => { translated.count++; return { t: (k: string) => k, i18n: { resolvedLanguage: 'en', language: 'en' } }; },
  Trans: ({ children }: { children?: unknown }) => children,
}));
vi.mock('../api/client', async (orig) => ({ ...(await orig<object>()), api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));

// Which strings went through the Markdown parser.
const parsed = vi.hoisted(() => [] as string[]);
vi.mock('react-markdown', async (orig) => {
  const real = await orig<typeof import('react-markdown')>();
  return { ...real, default: (props: Parameters<typeof real.default>[0]) => { parsed.push(String(props.children)); return real.default(props); } };
});

// BrandMark isn't memoized, so it renders whenever the chat does.
const chatRenders = vi.hoisted(() => ({ count: 0 }));
vi.mock('../components/BrandMark', () => ({ default: () => { chatRenders.count++; return null; } }));

import { toUiMessages } from '../api/adapters';
import MessageBody from '../components/MessageBody';
import OrchestratorChat from '../components/OrchestratorChat';
import ReplyFooter from '../components/reply/ReplyFooter';
import { useStreamingText } from '../hooks/useStreamingText';
import { splitBlocks } from '../lib/markdownBlocks';
import { initialArslanState, useArslanStore } from '../stores/arslanStore';
import type { Message } from '../types';

const store = () => useArslanStore.getState();
const frame = (f: object) => store().handleFrame(f as never);
const chunk = (content: string) => frame({ type: 'stream_chunk', content });

beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
beforeEach(() => { useArslanStore.setState(initialArslanState(), true); parsed.length = 0; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const REPLY = `# Clearing Downloads

Found **12 groups**, 1.8 GB, with \`shasum\`. See [the folder](https://example.com/d).

Second paragraph, right after the first.

- Installers
  - Keep the newest \`.dmg\`
- Photos

  A paragraph inside the second item.

- Documents

1. First
2. Second

    indented inside the second

Text between lists.

- [x] Compared
- [ ] Moved to the Trash

\`\`\`bash
shasum -a 256 ~/Downloads/*

# a blank line above, and this is still code

| sort
\`\`\`

~~~
tilde fence

\`\`\`
not a closing fence for a tilde one

~~~

    indented code

    still indented code

> [!NOTE]
> Moving to the Trash can be undone.

> A plain quote.

---

| Type | Count |
|:-----|------:|
| dmg  | 5     |

After the table. The last line has no newline at the end.`;

describe('copy under a reply', () => {
  const none = { runId: 1, entries: [], summary: { steps: 0, failed: 0, ms: 1, usage: null } };

  it('copies the whole reply as written, from an icon with no text, and says so', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    // With a preamble: the .md download drops one, and copy must not.
    const text = `Here is what I found.\n\n${REPLY}`;
    render(<ReplyFooter text={text} process={none} latest />);
    const button = screen.getByTitle('msg.copy');
    expect(button.textContent).toBe('');
    fireEvent.click(button);
    expect(writeText).toHaveBeenCalledExactlyOnceWith(text);
    await waitFor(() => expect(button.querySelector('.text-success')).not.toBeNull());
  });

  it('every finished reply has one, a long one too, and a reply still streaming has none', () => {
    const items = [
      { id: 1, kind: 'message', role: 'user', content: 'hello' },
      { id: 2, kind: 'message', role: 'arslan', content: 'short, and no steps' },
      { id: 3, kind: 'message', role: 'arslan', content: 'long '.repeat(600) },
    ];
    const history = toUiMessages(items as never);
    const props = { setChatHistory: vi.fn(), spawns: [], currentStyle: 'linear' as const, setCurrentStyle: vi.fn(), activeThread: null };
    const { rerender } = render(<OrchestratorChat {...props} chatHistory={history} />);
    expect(screen.getAllByTitle('msg.copy')).toHaveLength(2);
    rerender(<OrchestratorChat {...props} chatHistory={[...history, { id: '__streaming__', sender: 'arslan', senderName: 'Arslan', senderAvatar: '', text: 'going', timestamp: '' }]} />);
    expect(screen.getAllByTitle('msg.copy')).toHaveLength(2);
  });
});

describe('splitBlocks', () => {
  it('loses nothing, at any point of a stream', () => {
    for (let n = 0; n <= REPLY.length; n++) expect(splitBlocks(REPLY.slice(0, n)).join('')).toBe(REPLY.slice(0, n));
  });

  it('splits where a block has ended', () => {
    expect(splitBlocks('# Title\n\nOne.\n\nTwo.\n\n| a |\n|---|\n| 1 |\n\n> quote\n\nThree'))
      .toEqual(['# Title\n\n', 'One.\n\n', 'Two.\n\n', '| a |\n|---|\n| 1 |\n\n', '> quote\n\n', 'Three']);
  });

  it('a block with no blank line after it has not ended', () => {
    expect(splitBlocks('One.\nStill one.\n\n')).toEqual(['One.\nStill one.\n\n']);
  });

  it('an item of a loose list, or anything indented, belongs to what came before', () => {
    for (const whole of ['- a\n\n- b\n\n* c\n\n+ d\n\n', '1. a\n\n2. b\n\n3) c\n\n', '- a\n\n  more of a\n\n', 'para\n\n    code\n\n\tcode\n\n'])
      expect(splitBlocks(whole)).toEqual([whole]);
    expect(splitBlocks('- a\n\nAfter')).toEqual(['- a\n\n', 'After']);
    // Not a list marker: no space after it, so it is a paragraph of its own.
    expect(splitBlocks('a\n\n-b')).toEqual(['a\n\n', '-b']);
    expect(splitBlocks('a\n\n1.5 of them')).toEqual(['a\n\n', '1.5 of them']);
  });

  it('keeps a fence whole across blank lines, closed or not', () => {
    const fence = '```py\none\n\ntwo\n\nthree\n```\n\n';
    expect(splitBlocks(`${fence}After`)).toEqual([fence, 'After']);
    expect(splitBlocks('```py\none\n\ntwo')).toEqual(['```py\none\n\ntwo']);
    expect(splitBlocks('  ```\none\n\ntwo\n  ```  \n\nAfter')).toEqual(['  ```\none\n\ntwo\n  ```  \n\n', 'After']);
  });

  it('closes a fence only with the same character, at least as long, and nothing after it', () => {
    const open = (inner: string) => splitBlocks(`\`\`\`\`\none\n\n${inner}\n\nInside?`);
    for (const inner of ['```', '~~~~', '```` x', '    ````']) expect(open(inner)).toHaveLength(1);
    expect(open('````')).toHaveLength(2);
    expect(open('`````')).toHaveLength(2);
    expect(splitBlocks('~~~\none\n\n```\n\nInside?')).toHaveLength(1);
    expect(splitBlocks('~~~\none\n\n~~~\n\nAfter')).toHaveLength(2);
  });

  it('a line of backticks with more backticks after it is inline code, not a fence', () => {
    expect(splitBlocks('``` not a fence ```\n\nAfter\n\nMore')).toEqual(['``` not a fence ```\n\n', 'After\n\n', 'More']);
  });

  it('a fence with no language, four spaces in, is indented code and opens nothing', () => {
    expect(splitBlocks('    ```\n\nAfter\n\nMore')).toEqual(['    ```\n\n', 'After\n\n', 'More']);
  });
});

const CLASS = 'x';

/** What a reply draws: the wrappers that make blocks add no box, and whitespace between blocks draws nothing. */
function drawn(html: string): string {
  const host = document.createElement('div');
  host.innerHTML = html;
  for (const wrapper of [...host.querySelectorAll('div.contents')]) wrapper.replaceWith(...wrapper.childNodes);
  return host.querySelector('[data-md-root]')!.firstElementChild!.innerHTML.replace(/>\s+</g, '><');
}

describe('a live reply', () => {
  it('shows what the whole reply would show, at every point of the stream', () => {
    // Every line's first few characters, where a cut is decided, and a sample of the rest: all of them takes too long.
    const points = [...REPLY].flatMap((_, n) => (n % 11 === 0 || REPLY.slice(Math.max(0, n - 3), n).includes('\n') ? [n + 1] : []));
    for (const n of points) {
      const text = REPLY.slice(0, n);
      const live = drawn(renderToStaticMarkup(<MessageBody text={text} streaming className={CLASS} />));
      const whole = drawn(renderToStaticMarkup(<MessageBody text={text} className={CLASS} footerActions />));
      expect(live, `after ${n} characters`).toBe(whole);
    }
  }, 60_000);

  it('has the same class on its one wrapper, and each block adds no box', () => {
    const { container } = render(<MessageBody text={'One.\n\nTwo.'} streaming className={CLASS} />);
    const root = container.querySelector('[data-md-root]')!;
    expect(root.children).toHaveLength(1);
    expect(root.firstElementChild!.className).toBe(CLASS);
    expect([...root.firstElementChild!.children].map((c) => c.className)).toEqual(['contents', 'contents']);
  });

  it('parses again only the block still growing', () => {
    const first = '# Title\n\nOne.\n\n```py\nx = 1\n\ny = 2\n```\n\n';
    const { rerender } = render(<MessageBody text={`${first}Grow`} streaming />);
    expect(parsed).toEqual(['# Title\n\n', 'One.\n\n', '```py\nx = 1\n\ny = 2\n```\n\n', 'Grow']);
    parsed.length = 0;
    rerender(<MessageBody text={`${first}Growing`} streaming />);
    expect(parsed).toEqual(['Growing']);
    parsed.length = 0;
    rerender(<MessageBody text={`${first}Growing\n\nNext`} streaming />);
    expect(parsed).toEqual(['Growing\n\n', 'Next']);
  });

  it('a finished reply is parsed whole, once, so what only the whole can settle is settled', () => {
    const text = 'See [the docs][1].\n\n[1]: https://example.com/docs';
    const { container, rerender } = render(<MessageBody text={text} streaming />);
    parsed.length = 0;
    rerender(<MessageBody text={text} />);
    expect(parsed).toEqual([text]);
    expect(container.querySelector('a')!.getAttribute('href')).toBe('https://example.com/docs');
    expect(container.querySelector('div.contents')).toBeNull();
  });
});

/** Animation frames that run when the test says. */
function frames() {
  const pending = new Map<number, FrameRequestCallback>();
  let id = 0;
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => { pending.set(++id, cb); return id; });
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation((i) => { pending.delete(i); });
  return {
    pending: () => pending.size,
    run: () => act(() => { const due = [...pending.values()]; pending.clear(); due.forEach((cb) => cb(0)); }),
  };
}

describe('useStreamingText', () => {
  function watch() {
    const seen: string[] = [];
    const hook = renderHook(() => { const text = useStreamingText(); seen.push(text); return text; });
    return { ...hook, seen };
  }

  it('takes many chunks in one render, on the next frame', () => {
    const f = frames();
    const { result, seen } = watch();
    act(() => frame({ type: 'stream_start', source: 'arslan' }));
    seen.length = 0;
    act(() => { chunk('a'); chunk('b'); });
    act(() => chunk('c'));
    expect(seen).toEqual([]);
    expect(result.current).toBe('');
    expect(f.pending()).toBe(1);
    f.run();
    expect(seen).toEqual(['abc']);
    expect(f.pending()).toBe(0);
  });

  it('leaves the store exact: every character is there at once, and in the finished reply', () => {
    frames();
    watch();
    act(() => { frame({ type: 'stream_start', source: 'arslan' }); chunk('every '); chunk('character'); });
    expect(store().streamingText).toBe('every character');
    act(() => frame({ type: 'stream_end', message_id: 9 }));
    expect(store().items.at(-1)).toMatchObject({ content: 'every character' });
  });

  it('asks for no frame when nothing changed', () => {
    const f = frames();
    watch();
    act(() => frame({ type: 'note', text: 'not the reply' }));
    expect(f.pending()).toBe(0);
  });

  it('a new reply starts empty at once: the last reply never shows in its place, and a frame still due is dropped', () => {
    const f = frames();
    const { result } = watch();
    act(() => { frame({ type: 'stream_start', source: 'arslan' }); chunk('the last reply'); });
    f.run();
    expect(result.current).toBe('the last reply');
    act(() => chunk(', and more'));
    expect(f.pending()).toBe(1);
    act(() => frame({ type: 'stream_end', message_id: 9 }));
    expect(result.current).toBe('');
    expect(f.pending()).toBe(0);
    act(() => frame({ type: 'stream_start', source: 'arslan' }));
    expect(result.current).toBe('');
  });

  it('a reply sent back shrinks at once to what stays, then grows by frames again', () => {
    const f = frames();
    const { result } = watch();
    act(() => { frame({ type: 'stream_start', source: 'arslan' }); chunk('kept. wrong draft'); });
    f.run();
    act(() => frame({ type: 'stream_restart', label: 'x', keep: 'kept.' }));
    expect(result.current).toBe('kept.');
    expect(f.pending()).toBe(0);
    act(() => chunk(' right'));
    expect(result.current).toBe('kept.');
    f.run();
    expect(result.current).toBe('kept. right');
  });

  it('a new window starts from what the store has, and an unmount drops a frame still due', () => {
    const f = frames();
    act(() => { frame({ type: 'stream_start', source: 'arslan' }); chunk('already here'); });
    const { result, unmount } = watch();
    expect(result.current).toBe('already here');
    act(() => chunk(' and more'));
    expect(f.pending()).toBe(1);
    unmount();
    expect(f.pending()).toBe(0);
  });
});

describe('the chat while a reply streams', () => {
  const props = { setChatHistory: vi.fn(), spawns: [], currentStyle: 'linear' as const, setCurrentStyle: vi.fn(), activeThread: null };
  const history = toUiMessages([{ id: 1, kind: 'message', role: 'arslan', content: 'An earlier reply.' }] as never);

  it('does not render again for a frame with no new step of its own: the timestamp every frame moves is not its business', () => {
    let now = 1_000_000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    render(<OrchestratorChat {...props} chatHistory={history} />);
    act(() => { frame({ type: 'stream_start', source: 'arslan' }); chunk('first'); });
    chatRenders.count = 0;
    for (const word of [' one', ' two', ' three']) { now += 20; act(() => chunk(word)); }
    expect(store().lastStepAt).toBe(now);
    expect(chatRenders.count).toBe(0);
  });

  it('still tells a long quiet from a live turn: a frame clears "still working"', () => {
    let now = 1_000_000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    useArslanStore.setState({ thinking: true, workStartedAt: now - 200_000, lastStepAt: now - 61_000 });
    render(<OrchestratorChat {...props} chatHistory={history} />);
    expect(screen.getByText('working.long')).toBeInTheDocument();
    now += 20;
    act(() => frame({ type: 'tool_call', tool: 'web_search', args_summary: '{}' }));
    expect(screen.queryByText('working.long')).toBeNull();
    expect(screen.getByText('working.thinking')).toBeInTheDocument();
  });
});

describe('a finished reply while the chat renders', () => {
  const process = { runId: 1, entries: [], summary: { steps: 0, failed: 0, ms: 1, usage: null } };
  const onReplay = vi.fn();

  it('its body sits it out', () => {
    const { rerender } = render(<MessageBody text="Done." className={CLASS} footerActions />);
    translated.count = 0;
    rerender(<MessageBody text="Done." className={CLASS} footerActions />);
    expect(translated.count).toBe(0);
    rerender(<MessageBody text="Done, and more." className={CLASS} footerActions />);
    expect(translated.count).toBeGreaterThan(0);
  });

  it('its footer sits it out, until it stops being the latest reply', () => {
    const { rerender } = render(<ReplyFooter text="Done." process={process} latest onReplay={onReplay} />);
    translated.count = 0;
    rerender(<ReplyFooter text="Done." process={process} latest onReplay={onReplay} />);
    expect(translated.count).toBe(0);
    rerender(<ReplyFooter text="Done." process={process} latest={false} onReplay={onReplay} />);
    expect(translated.count).toBeGreaterThan(0);
  });
});

describe('composing Chinese while a reply streams', () => {
  // A write to the box's value during a composition ends it in a real input method: nothing but the method may write there.
  const native = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!;
  let writes: string[];
  beforeEach(() => {
    writes = [];
    Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {
      configurable: true, get: native.get, set(v: string) { writes.push(v); native.set!.call(this, v); },
    });
  });
  afterEach(() => { Object.defineProperty(HTMLTextAreaElement.prototype, 'value', native); });

  const before: Message[] = [{ id: '1', sender: 'user', senderName: 'You', senderAvatar: '', text: 'hello', timestamp: '' }];

  /** What App does: the live reply is one more message, with the text from the hook. */
  function Chat({ onSendMessage }: { onSendMessage: (text: string) => void }) {
    const text = useStreamingText();
    const streaming = useArslanStore((s) => s.streaming);
    const history = useArslanStore((s) => s.items);
    return <OrchestratorChat conversationId="ime" setChatHistory={vi.fn()} spawns={[]} currentStyle="linear" setCurrentStyle={vi.fn()} activeThread={null}
      onSendMessage={onSendMessage}
      chatHistory={[...before, ...toUiMessages(history),
        ...(streaming && text ? [{ id: '__streaming__', sender: 'arslan' as const, senderName: 'Arslan', senderAvatar: '', text, timestamp: '' }] : [])]} />;
  }

  function composer() {
    const f = frames();
    const onSendMessage = vi.fn();
    const { container } = render(<Chat onSendMessage={onSendMessage} />);
    const box = container.querySelector('#chat-message-input') as HTMLTextAreaElement;
    box.focus();
    /** One keystroke of an input method: it writes the box itself, then says so. */
    const key = (value: string) => {
      fireEvent.compositionUpdate(box, { data: value });
      fireEvent.input(box, { target: { value } });
      writes.length = 0;
    };
    /** Tokens and a frame land between two keystrokes. */
    const tokens = (content: string) => { act(() => chunk(content)); f.run(); };
    return { box, key, tokens, onSendMessage };
  }

  it('nothing writes to the box, and what the method wrote stays, through tokens between keystrokes', () => {
    const { box, key, tokens } = composer();
    act(() => frame({ type: 'stream_start', source: 'arslan' }));
    tokens('Looking ');
    fireEvent.compositionStart(box, { data: '' });
    for (const [i, value] of ['n', 'ni', 'ni h', 'ni ha', 'ni hao'].entries()) {
      key(value);
      tokens(`at the folder, part ${i}.\n\n`);
      expect(box).toHaveFocus();
      expect(box.value).toBe(value);
      expect(writes).toEqual([]);
    }
    expect(screen.getByText('at the folder, part 4.')).toBeInTheDocument();
  });

  it('what is confirmed goes out once and whole, with the reply ending in the middle of the composition', () => {
    const { box, key, tokens, onSendMessage } = composer();
    act(() => frame({ type: 'stream_start', source: 'arslan' }));
    tokens('Looking.');
    fireEvent.compositionStart(box, { data: '' });
    key('ni hao');
    act(() => frame({ type: 'stream_end', message_id: 9 }));
    expect(box.value).toBe('ni hao');
    expect(writes).toEqual([]);
    // WebKit: the Enter that confirms has keyCode 229, and must only confirm.
    fireEvent.keyDown(box, { key: 'Enter', keyCode: 229 });
    expect(onSendMessage).not.toHaveBeenCalled();
    fireEvent.compositionUpdate(box, { data: '你好' });
    fireEvent.input(box, { target: { value: '你好' } });
    fireEvent.compositionEnd(box, { data: '你好' });
    writes.length = 0;
    act(() => frame({ type: 'stream_start', source: 'arslan' }));
    tokens('Next reply.');
    expect(box.value).toBe('你好');
    expect(writes).toEqual([]);
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSendMessage).toHaveBeenCalledExactlyOnceWith('你好', undefined);
    expect(box.value).toBe('');
  });
});

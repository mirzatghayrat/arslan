/**
 * FMT1 PR 3 (0.1.64): what only the real App shows, on a fake socket and a stubbed fetch. The live text reaches the chat once
 * per frame, and nothing renders the chat in between. A finished reply's footer keeps its props across those frames. A chat
 * following the bottom follows a model-error notice, or the way out of a failed model lands below the fold. A first reply gets
 * one title.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Not memoized here, so it renders whenever the chat does, and shows what the chat handed it.
const footer = vi.hoisted(() => ({ props: [] as { process: unknown }[] }));
vi.mock('../components/reply/ReplyFooter', async (orig) => ({
  ...(await orig<object>()),
  default: (props: { process: unknown }) => { footer.props.push(props); return null; },
}));

import '../i18n';
import App from '../App';
import { initialArslanState, useArslanStore } from '../stores/arslanStore';

class FakeSocket {
  static OPEN = 1;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) { sockets.push(this); queueMicrotask(() => this.onopen?.()); }
  send() {}
  close() {}
}
let sockets: FakeSocket[];
let titles: string[];
const realSocket = globalThis.WebSocket;

const LISTS = /brain\/notes|brain\/proposals|collections|conversations|facts|runs|scheduled-tasks|spawns|settings\/(providers|search-providers)/;
function reply(url: string, init?: RequestInit): unknown {
  if (url.includes('/orchestrator/title')) { titles.push(JSON.parse(String(init?.body)).first_message); return { title: 'A title' }; }
  if (/provider-configs\/\d+\/models/.test(url)) return { models: [] };
  if (url.includes('provider-configs')) return [{ id: 1, provider: 'a', model: 'one', label: 'A', is_primary: true }, { id: 2, provider: 'b', model: 'two', label: 'B', is_primary: false }];
  if (LISTS.test(url)) return [];
  return /\/settings(\?|$)/.test(url) ? { first_run_seen: true, language: 'en' } : {};
}

const frame = (f: object) => act(() => { sockets.filter((s) => s.url.includes('/ws/arslan/')).at(-1)!.onmessage!({ data: JSON.stringify(f) }); });

const ask = (text: string) => act(() => useArslanStore.getState().addUserMessage(text));
const settled = () => act(async () => { await new Promise((r) => setTimeout(r, 20)); });

/** A reply through the real socket path. */
async function answer(text: string, id: number) {
  frame({ type: 'stream_start', run_id: id });
  frame({ type: 'stream_chunk', content: text });
  frame({ type: 'stream_end', message_id: id, run_id: id });
  await screen.findByText(text);
}

/** The chat's scroller at its top, with the height jsdom can't give it. */
function scroller() {
  const box = screen.getByText('An earlier reply.').closest('.overflow-y-auto') as HTMLElement;
  let top = 0;
  Object.defineProperty(box, 'scrollHeight', { configurable: true, value: 5000 });
  Object.defineProperty(box, 'scrollTop', { configurable: true, get: () => top, set: (v: number) => { top = v; } });
  return box;
}

beforeEach(async () => {
  sockets = [];
  titles = [];
  footer.props = [];
  localStorage.clear();
  sessionStorage.clear();
  useArslanStore.setState(initialArslanState(), true);
  globalThis.WebSocket = FakeSocket as never;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) =>
    new Response(JSON.stringify(reply(String(input), init)), { status: 200, headers: { 'content-type': 'application/json' } }));
  render(<App />);
  await waitFor(() => expect(sockets.some((s) => s.url.includes('/ws/arslan/'))).toBe(true));
  await settled();
});
afterEach(() => { cleanup(); globalThis.WebSocket = realSocket; vi.restoreAllMocks(); });

describe('the real App while a reply streams', () => {
  it('shows the live text on the next frame, and nothing renders the chat in between', async () => {
    ask('first');
    await answer('An earlier reply.', 1);
    const due: FrameRequestCallback[] = [];
    vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => { due.push(cb); return due.length; });
    frame({ type: 'stream_start', run_id: 2 });
    footer.props = [];
    frame({ type: 'stream_chunk', content: 'Live ' });
    frame({ type: 'stream_chunk', content: 'text.' });
    expect(useArslanStore.getState().streamingText).toBe('Live text.');
    expect(screen.queryByText('Live text.')).toBeNull();
    expect(footer.props).toEqual([]);
    act(() => due.splice(0).forEach((cb) => cb(0)));
    expect(screen.getByText('Live text.')).toBeInTheDocument();
    expect(footer.props.length).toBeGreaterThan(0);
  });

  it("hands a finished reply's footer the same process on every frame, or its memo would do nothing", async () => {
    ask('first');
    await answer('An earlier reply.', 1);
    const before = footer.props.at(-1)!.process;
    frame({ type: 'stream_start', run_id: 2 });
    frame({ type: 'stream_chunk', content: 'Live text.' });
    await screen.findByText('Live text.');
    expect(footer.props.at(-1)!.process).toBe(before);
  });

  it('shows a change to an item, with no change in how many there are', async () => {
    ask('first');
    await answer('An earlier reply.', 1);
    act(() => useArslanStore.setState((s) => ({ items: s.items.map((item) => (item.id === 1 ? { ...item, content: 'Edited.' } : item)) })));
    expect(await screen.findByText('Edited.')).toBeInTheDocument();
  });
});

describe('a model error', () => {
  const error = { type: 'error', message: 'The model refused.', call: { role: 'chat', provider: 'a', model: 'one' } };

  it('the chat follows it, so the way out of a failed model is in view', async () => {
    ask('first');
    await answer('An earlier reply.', 1);
    const box = scroller();
    frame(error);
    expect(screen.getByTestId('chat-error-switch')).toBeInTheDocument();
    expect(box.scrollTop).toBe(5000);
  });

  it('leaves alone someone who scrolled up', async () => {
    ask('first');
    await answer('An earlier reply.', 1);
    const box = scroller();
    fireEvent.scroll(box);        // far from the bottom: 5000 tall, at 0
    frame(error);
    expect(screen.getByTestId('chat-error-switch')).toBeInTheDocument();
    expect(box.scrollTop).toBe(0);
  });
});

describe('the title', () => {
  it('one once the first reply is in, from the first message only, and no more after it', async () => {
    ask('the first question');
    await settled();
    expect(titles).toEqual([]);
    await answer('The first reply.', 1);
    await waitFor(() => expect(titles).toEqual(['the first question']));
    // Still one exchange: a job's result, say, arrives before the user writes again.
    act(() => useArslanStore.setState((s) => ({ items: [...s.items, { id: 3, kind: 'message', role: 'arslan', content: 'A job finished.' }] })));
    await settled();
    expect(titles).toEqual(['the first question']);
    ask('another question');
    await answer('The second reply.', 2);
    await settled();
    expect(titles).toEqual(['the first question']);
  });
});

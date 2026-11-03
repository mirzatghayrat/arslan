import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { toUiMessages } from '../api/adapters';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import type { Message } from '../types';

/**
 * K8a follow-up (user report via ①iOS, 2026-11-03): one message showed the same answer four times, each after
 * "Correction: part of the answer above was not right…". A guard that sends back text which already went out now
 * replaces it: the server sends `stream_restart` with a label, and the window keeps what went out as a collapsed
 * earlier draft above the answer. The reply's text is the answer alone (the server stores only that). The server
 * half is tests/server/test_k8a_one_answer.py.
 */
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const LABEL = '较早的草稿，已替换：其中有一部分不对。';
const store = () => useArslanStore.getState();
const base = {
  setChatHistory: vi.fn(), spawns: [] as never[], currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(), activeThread: null, onSendMessage: vi.fn(),
};

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
});

function turn(...frames: object[]) {
  store().handleFrame({ type: 'stream_start', source: 'arslan' } as never);
  for (const frame of frames) store().handleFrame(frame as never);
}

describe('a replaced answer', () => {
  it('keeps what went out as an earlier draft, and the reply is the answer alone', () => {
    turn({ type: 'stream_chunk', content: 'first ' }, { type: 'stream_chunk', content: 'draft' },
         { type: 'stream_restart', label: LABEL }, { type: 'stream_chunk', content: 'the answer' });
    expect(store().streamingText).toBe('the answer');
    expect(store().streamingDrafts).toEqual([{ label: LABEL, text: 'first draft' }]);
    store().handleFrame({ type: 'stream_end', message_id: 9 } as never);
    const [reply] = store().items;
    expect(reply.content).toBe('the answer');
    expect(reply.drafts).toEqual([{ label: LABEL, text: 'first draft' }]);
    expect(store().streamingDrafts).toEqual([]);
  });

  it('keeps every draft in order (the report had three)', () => {
    turn({ type: 'stream_chunk', content: 'one' }, { type: 'stream_restart', label: LABEL },
         { type: 'stream_chunk', content: 'two' }, { type: 'stream_restart', label: LABEL },
         { type: 'stream_chunk', content: 'three' }, { type: 'stream_restart', label: LABEL },
         { type: 'stream_chunk', content: 'answer' }, { type: 'stream_end', message_id: 9 });
    const [reply] = store().items;
    expect(reply.content).toBe('answer');
    expect(reply.drafts?.map((d) => d.text)).toEqual(['one', 'two', 'three']);
  });

  it('a restart with nothing shown adds no draft', () => {
    turn({ type: 'stream_restart', label: LABEL }, { type: 'stream_chunk', content: 'answer' },
         { type: 'stream_end', message_id: 9 });
    expect(store().items[0].drafts).toBeUndefined();
  });

  it('a new turn and the history start with no drafts', () => {
    turn({ type: 'stream_chunk', content: 'draft' }, { type: 'stream_restart', label: LABEL },
         { type: 'error', code: 'x', message: 'failed' });
    expect(store().streamingDrafts).toEqual([]);
    turn({ type: 'stream_chunk', content: 'draft' }, { type: 'stream_restart', label: LABEL });
    store().handleFrame({ type: 'stream_start', source: 'arslan' } as never);
    expect(store().streamingDrafts).toEqual([]);
  });

  it('a cancelled reply keeps its drafts with its partial answer', () => {
    turn({ type: 'stream_chunk', content: 'draft' }, { type: 'stream_restart', label: LABEL },
         { type: 'stream_chunk', content: 'partial' }, { type: 'run_cancelled', run_id: 3 });
    const [reply] = store().items;
    expect(reply.content).toBe('partial');
    expect(reply.drafts).toEqual([{ label: LABEL, text: 'draft' }]);
  });
});

describe('the bubble', () => {
  it('shows the draft collapsed under its label, above the answer', () => {
    turn({ type: 'stream_chunk', content: 'the old draft text' }, { type: 'stream_restart', label: LABEL },
         { type: 'stream_chunk', content: 'the answer' }, { type: 'stream_end', message_id: 9 });
    const chatHistory: Message[] = toUiMessages(store().items);
    render(<OrchestratorChat {...base} chatHistory={chatHistory} />);
    const drafts = screen.getByTestId('earlier-drafts');
    const details = drafts.querySelector('details');
    expect(details?.open).toBe(false);                                   // collapsed
    expect(details?.querySelector('summary')?.textContent).toBe(LABEL);
    expect(drafts.textContent).toContain('the old draft text');
    expect(screen.getByText('the answer')).toBeTruthy();
    expect(drafts.compareDocumentPosition(screen.getByText('the answer')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('a reply with no drafts shows none', () => {
    const chatHistory: Message[] = [
      { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
    ];
    render(<OrchestratorChat {...base} chatHistory={chatHistory} />);
    expect(screen.queryByTestId('earlier-drafts')).toBeNull();
  });
});

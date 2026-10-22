import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import type { Message } from '../types';

/**
 * 0.1.63 K9b: a message sent while a reply runs is added to that reply at its next step (the server half is
 * tests/server/test_k9b_steering.py). The window says so, and the reply keeps its own timer.
 */
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
vi.mock('../components/PushToTalk', () => ({
  default: (props: { onFinal: (text: string) => void }) => (
    <button type="button" data-testid="ptt-final" onClick={() => props.onFinal('also check the logs')}>final</button>
  ),
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];
const store = () => useArslanStore.getState();

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
});

function props(onSendMessage = vi.fn()) {
  return {
    chatHistory: history, setChatHistory: vi.fn(), spawns: [] as never[], currentStyle: 'quartz' as const,
    setCurrentStyle: vi.fn(), activeThread: null, onSendMessage,
  };
}

describe('a message added to the running reply', () => {
  it('says it was added, and the running reply keeps its timer', () => {
    store().handleFrame({ type: 'stream_start', source: 'arslan' } as never);
    const started = Date.now() - 40_000;
    useArslanStore.setState({ workStartedAt: started, thinking: true });
    store().handleFrame({ type: 'queued' } as never);
    store().handleFrame({ type: 'dequeued', inserted: true } as never);
    expect(store().queued).toBe(false);
    expect(store().inserted).toBe(true);
    expect(store().workStartedAt).toBe(started);
    render(<OrchestratorChat {...props()} />);
    expect(screen.getByTestId('inserted-notice').textContent).toBe('working.inserted');
    expect(screen.queryByTestId('queued-notice')).toBeNull();
  });

  it('the notice goes when that reply ends', () => {
    store().handleFrame({ type: 'stream_start', source: 'arslan' } as never);
    store().handleFrame({ type: 'dequeued', inserted: true } as never);
    store().handleFrame({ type: 'stream_end', message_id: null } as never);
    expect(store().inserted).toBe(false);
  });

  it('a plain dequeued still starts its own turn', () => {
    store().handleFrame({ type: 'queued' } as never);
    store().handleFrame({ type: 'dequeued' } as never);
    expect(store().inserted).toBe(false);
    expect(store().thinking).toBe(true);
  });

  it('hold-to-talk: the final text fills the box, and sending while a reply streams sends it', () => {
    const onSendMessage = vi.fn();
    store().handleFrame({ type: 'stream_start', source: 'arslan' } as never);
    expect(store().streaming).toBe(true);
    const { container } = render(<OrchestratorChat {...props(onSendMessage)} />);
    fireEvent.click(screen.getByTestId('ptt-final'));
    expect((container.querySelector('#chat-message-input') as HTMLInputElement).value).toBe('also check the logs');
    fireEvent.click(container.querySelector('#chat-send-submit') as HTMLButtonElement);
    expect(onSendMessage).toHaveBeenCalledWith('also check the logs', undefined);
  });
});

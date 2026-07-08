import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import type { Message } from '../types';

/**
 * HX-4 / A1 — working indicators are driven ONLY by runtime frames.
 *  - active turn → LiveActivity pulse visible;
 *  - stalled turn (>90s without frames) → static 「已中断」, no pulse, no pill shimmer;
 *  - after stream_end → nothing;
 *  - regression (the live incident): a message whose TEXT says "正在生成中,稍等"
 *    with no active flags must render NO working indicator.
 */
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];
const spawns = [{ id: '3', name: 'Deck Master', domain: 'decks', avatarEmoji: '🎴', status: 'idle' }] as never[];
const base = {
  chatHistory: history, setChatHistory: vi.fn(), spawns, currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(), activeThread: null, onSendMessage: vi.fn(),
};

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
});

describe('OrchestratorChat working indicators (HX-4 / A1)', () => {
  it('active turn → LiveActivity pulse visible, no stalled marker', () => {
    useArslanStore.setState({ thinking: true, workStartedAt: Date.now(), lastFrameAt: Date.now() });
    render(<OrchestratorChat {...base} />);
    expect(screen.getByTestId('live-activity')).toBeTruthy();
    expect(screen.queryByTestId('stalled-indicator')).toBeNull();
  });

  it('stalled turn → 「已中断」 rendered, pulse gone, pill shimmer stopped', () => {
    useArslanStore.setState({
      thinking: true,
      workStartedAt: Date.now(),
      stalled: true,
      roster: [{ spawnId: 3, spawnName: 'Deck Master', joinedVia: 'invite', status: 'idle' }],
      pendingRoute: { spawnId: 3, spawnName: 'Deck Master' },
    } as never);
    const { container } = render(<OrchestratorChat {...base} />);
    const marker = screen.getByTestId('stalled-indicator');
    expect(marker.textContent).toContain('working.stalled');
    // No animated pulse block, no spinner, no pill shimmer while stalled.
    expect(screen.queryByTestId('live-activity')).toBeNull();
    expect(container.querySelector('.shiny-text')).toBeNull();
  });

  it('after stream_end → neither pulse nor stalled marker', () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: 'stream_start', source: 'arslan' } as never);
    useArslanStore.getState().handleFrame({ type: 'stream_chunk', content: 'ok' } as never);
    useArslanStore.getState().handleFrame({ type: 'stream_end', message_id: 9 } as never);
    render(<OrchestratorChat {...base} />);
    expect(screen.queryByTestId('live-activity')).toBeNull();
    expect(screen.queryByTestId('stalled-indicator')).toBeNull();
  });

  it('REGRESSION (live incident): "正在生成中,稍等" in message TEXT with no active flags renders no working indicator', () => {
    const incident: Message[] = [
      { id: 'm1', sender: 'user', senderName: 'You', senderAvatar: '🦁', text: '帮我做个 ppt', timestamp: '10:00' },
      { id: 'm2', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'Deck Master 正在生成中,稍等', timestamp: '10:01' },
    ];
    const { container } = render(<OrchestratorChat {...base} chatHistory={incident} />);
    // Message text must never drive a "working" visual.
    expect(screen.queryByTestId('live-activity')).toBeNull();
    expect(screen.queryByTestId('stalled-indicator')).toBeNull();
    expect(container.querySelector('.shiny-text')).toBeNull();
  });
});

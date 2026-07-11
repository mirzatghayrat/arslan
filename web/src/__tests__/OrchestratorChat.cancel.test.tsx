import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import { toUiMessages } from '../api/adapters';
import type { Message } from '../types';
import type { ArslanThreadItem } from '../api/client.types';

/**
 * S3-M1 Task 7 — stop button + cancelled marker.
 *
 * Invariants under test:
 *  - activeRunId != null → the composer shows a stop button; clicking it POSTs
 *    api.cancelRun(activeRunId) exactly once (pending-latch blocks double-POST);
 *  - activeRunId == null → NO stop button, even while thinking/turnActive
 *    (an unrecorded arslan turn has no cancel target);
 *  - an item with cancelled:true renders the muted interrupted marker
 *    (reuses the stall indicator's existing `working.stalled` key — same
 *    translations in all 6 locales, no duplicate key added).
 */

// vi.hoisted per repo gotcha (vi.mock is hoisted above const declarations).
const { cancelRun } = vi.hoisted(() => ({ cancelRun: vi.fn(async () => ({ ok: true })) }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({
  api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn(), cancelRun },
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const history: Message[] = [
  { id: 'm1', sender: 'user', senderName: 'You', senderAvatar: '🦁', text: '查一下', timestamp: '10:00' },
];
const spawns = [{ id: '3', name: 'Deck Master', domain: 'decks', avatarEmoji: '🎴', status: 'idle' }] as never[];
const base = {
  chatHistory: history, setChatHistory: vi.fn(), spawns, currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(), activeThread: null, onSendMessage: vi.fn(),
};

beforeEach(() => {
  cancelRun.mockClear();
  useArslanStore.setState(initialArslanState(), true);
});

describe('OrchestratorChat stop button (S3-M1)', () => {
  it('streaming with activeRunId=42 → stop button rendered; click calls api.cancelRun(42) once', () => {
    useArslanStore.setState({
      streaming: true, activeRunId: 42, workStartedAt: Date.now(), lastFrameAt: Date.now(),
    } as never);
    render(<OrchestratorChat {...base} />);
    const stop = screen.getByTitle('chat.stopRun');
    fireEvent.click(stop);
    expect(cancelRun).toHaveBeenCalledWith(42);
    // Pending latch: the button disables after the click → no double-POST.
    expect((stop as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(stop);
    expect(cancelRun).toHaveBeenCalledTimes(1);
  });

  it('no stop button when activeRunId is null, even while thinking/turnActive', () => {
    useArslanStore.setState({
      thinking: true, workStartedAt: Date.now(), lastFrameAt: Date.now(),
    } as never);
    render(<OrchestratorChat {...base} />);
    expect(screen.queryByTitle('chat.stopRun')).toBeNull();
  });

  it('no stop button when idle', () => {
    render(<OrchestratorChat {...base} />);
    expect(screen.queryByTitle('chat.stopRun')).toBeNull();
  });
});

describe('OrchestratorChat cancelled marker (S3-M1)', () => {
  it('an item with cancelled:true renders the muted interrupted marker', () => {
    const items: ArslanThreadItem[] = [
      { id: 9, kind: 'message', role: 'spawn', content: '写到一半的部分产出', spawnId: 3, spawnName: 'Deck Master', cancelled: true },
    ];
    render(<OrchestratorChat {...base} chatHistory={toUiMessages(items)} />);
    const marker = screen.getByTestId('run-cancelled-marker');
    // Reuses the stall indicator's key — identical wording (已中断/Interrupted/…).
    expect(marker.textContent).toContain('working.stalled');
    // Partial text stays visible above the marker.
    expect(screen.getByText(/写到一半的部分产出/)).toBeTruthy();
  });

  it('a normal item renders NO interrupted marker', () => {
    const items: ArslanThreadItem[] = [
      { id: 10, kind: 'message', role: 'spawn', content: '完整交付', spawnId: 3, spawnName: 'Deck Master' },
    ];
    render(<OrchestratorChat {...base} chatHistory={toUiMessages(items)} />);
    expect(screen.queryByTestId('run-cancelled-marker')).toBeNull();
  });
});

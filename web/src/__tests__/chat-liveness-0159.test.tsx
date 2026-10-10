import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { shortProvider } from '../components/models/ConversationModelChip';
import { chatTaskErrorKey, taskErrorKey } from '../components/companion/errors';
import { useArslanStore, initialArslanState, STALL_MS } from '../stores/arslanStore';
import type { Message } from '../types';

/**
 * 0.1.59 (run 160 on the user's Mac): a five-minute write showed "Interrupted", the follow-up was
 * refused with the edit-conflict text and lost, the live row said "Summoning specialist…", and the
 * model chip hid the model behind "OpenRouter (Claude, Gemini and mo…".
 * Spec: docs/specs/2026-10-11-0159-chat-liveness.md (D–F; the server half is in
 * tests/server/test_chat_liveness_0159.py).
 */
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];
const base = {
  chatHistory: history, setChatHistory: vi.fn(), spawns: [] as never[], currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(), activeThread: null, onSendMessage: vi.fn(),
};
const store = () => useArslanStore.getState();

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
});

describe('a long answer is not "Interrupted"', () => {
  it('the server\'s "working" beat keeps the watchdog quiet past 90 s, but is not a step', () => {
    const longAgo = Date.now() - STALL_MS - 5_000;
    useArslanStore.setState({ thinking: true, workStartedAt: longAgo, lastFrameAt: longAgo, lastStepAt: longAgo });
    store().handleFrame({ type: 'working', elapsed_s: 95 } as never);
    store().checkStall();
    expect(store().stalled).toBe(false);
    expect(store().lastStepAt).toBe(longAgo);            // the row may still say "a long answer…"
    render(<OrchestratorChat {...base} />);
    expect(screen.getByText('working.long')).toBeTruthy();
    expect(screen.queryByTestId('stalled-indicator')).toBeNull();
  });

  it('without any frame for 90 s it still says the connection went quiet', () => {
    const longAgo = Date.now() - STALL_MS - 5_000;
    useArslanStore.setState({ thinking: true, workStartedAt: longAgo, lastFrameAt: longAgo });
    store().checkStall();
    expect(store().stalled).toBe(true);
  });

  it('a real step resets the quiet clock', () => {
    const longAgo = Date.now() - 70_000;
    useArslanStore.setState({ thinking: true, workStartedAt: longAgo, lastFrameAt: longAgo, lastStepAt: longAgo });
    store().handleFrame({ type: 'tool_call', tool: 'write_file', args_summary: '{}' } as never);
    expect(store().lastStepAt).toBeGreaterThan(longAgo);
  });
});

describe('a second message waits its turn', () => {
  it('queued shows the notice; dequeued starts its own turn', () => {
    store().handleFrame({ type: 'queued' } as never);
    expect(store().queued).toBe(true);
    const { unmount } = render(<OrchestratorChat {...base} />);
    expect(screen.getByTestId('queued-notice').textContent).toBe('working.queued');
    unmount();
    store().handleFrame({ type: 'dequeued' } as never);
    expect(store().queued).toBe(false);
    expect(store().thinking).toBe(true);
    render(<OrchestratorChat {...base} />);
    expect(screen.queryByTestId('queued-notice')).toBeNull();
    expect(screen.getByTestId('live-activity')).toBeTruthy();
  });

  it('sending while a reply streams keeps that reply\'s timer', () => {
    store().handleFrame({ type: 'stream_start', source: 'arslan' } as never);
    const started = Date.now() - 40_000;
    useArslanStore.setState({ workStartedAt: started });
    store().addUserMessage('second: still there?');
    store().setThinking(true);
    expect(store().workStartedAt).toBe(started);
  });

  it('a refused chat turn says Arslan was still busy, not the edit-conflict text', () => {
    expect(chatTaskErrorKey('task_version_conflict')).toBe('tasks.chatBusy');
    expect(chatTaskErrorKey('task_attempt_stale')).toBe('tasks.chatBusy');
    expect(chatTaskErrorKey('task_budget_exhausted')).toBe(taskErrorKey('task_budget_exhausted'));
    expect(taskErrorKey('task_version_conflict')).toBe('companion.conflict');   // the task panel keeps it
    store().handleFrame({ type: 'error', code: 'TASK_REVIEW_REQUIRED', message: 'task_version_conflict', recoverable: true } as never);
    render(<OrchestratorChat {...base} />);
    expect(screen.getByTestId('chat-error').textContent).toContain('tasks.chatBusy');
    expect(screen.getByTestId('chat-error').textContent).not.toContain('companion.conflict');
  });
});

describe('the model chip', () => {
  it('names the provider short so the model stays readable', () => {
    expect(shortProvider('OpenRouter (Claude, Gemini and more)')).toBe('OpenRouter');
    expect(shortProvider('OpenRouter（Claude、Gemini 等）')).toBe('OpenRouter');
    expect(shortProvider('DeepSeek')).toBe('DeepSeek');
    expect(shortProvider('(local)')).toBe('(local)');
  });
});

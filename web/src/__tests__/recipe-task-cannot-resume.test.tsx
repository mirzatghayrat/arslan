import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { chatTaskErrorKey, taskErrorKey } from '../components/companion/errors';
import { taskMessages } from '../locales/tasks';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import type { Message } from '../types';

/**
 * C7b-3 (v0.1.63): recipes were removed. Resuming a task an old recipe saved is refused by the
 * server with `task_invalid_driver` (tests/server/test_recipe_driver_retired.py). The window must
 * say so in a sentence — as a task notice, not as a "Model error" with a raw code.
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

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
});

describe('an old recipe task that cannot be resumed', () => {
  it('maps the refusal to its own sentence in the chat and the task panel', () => {
    expect(chatTaskErrorKey('task_invalid_driver')).toBe('tasks.cannotResume');
    expect(taskErrorKey('task_invalid_driver')).toBe('tasks.cannotResume');
  });

  it('every language has the sentence', () => {
    for (const [lang, messages] of Object.entries(taskMessages)) {
      expect(messages.cannotResume, lang).toMatch(/\S{3,}/);
    }
  });

  it('shows as a task notice, not a model error with a raw code', () => {
    useArslanStore.getState().handleFrame({ type: 'error', code: 'TASK_REVIEW_REQUIRED',
      message: 'task_invalid_driver', recoverable: true } as never);
    render(<OrchestratorChat {...base} />);
    const box = screen.getByTestId('chat-error');
    expect(box.getAttribute('data-kind')).toBe('task');
    expect(box.textContent).toContain('tasks.cannotResume');
    expect(box.textContent).not.toContain('task_invalid_driver');
  });
});

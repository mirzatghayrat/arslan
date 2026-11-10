import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { chatTaskErrorKey, taskErrorKey } from '../components/companion/errors';
import { taskMessages } from '../locales/tasks';
import { proactiveMessages } from '../locales/proactive';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import type { Message } from '../types';

/**
 * SUB5a (v0.1.64): a conversation deleted elsewhere (the phone, another window) refuses every turn with
 * `conversation_deleted` (tests/server/test_sub5a_lifecycle.py). The window says so in a sentence, as a task notice,
 * not as a "Model error" with the raw code. An Inbox item for such a conversation is refused at accept, in words.
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

describe('a turn refused because its conversation was deleted', () => {
  it('maps the code to its own sentence in the chat and the task panel', () => {
    expect(chatTaskErrorKey('conversation_deleted')).toBe('tasks.conversationDeleted');
    expect(taskErrorKey('conversation_deleted')).toBe('tasks.conversationDeleted');
  });

  it('every language has the sentences', () => {
    for (const [lang, messages] of Object.entries(taskMessages)) {
      expect(messages.conversationDeleted, lang).toMatch(/\S{3,}/);
    }
    for (const [lang, messages] of Object.entries(proactiveMessages as Record<string, any>)) {
      expect(messages.item.errors.conversation_deleted, lang).toMatch(/\S{3,}/);
    }
  });

  it('shows as a task notice, not a model error with a raw code', () => {
    useArslanStore.getState().handleFrame({ type: 'error', code: 'TASK_REVIEW_REQUIRED',
      message: 'conversation_deleted', recoverable: true } as never);
    render(<OrchestratorChat {...base} />);
    const box = screen.getByTestId('chat-error');
    expect(box.getAttribute('data-kind')).toBe('task');
    expect(box.textContent).toContain('tasks.conversationDeleted');
    expect(box.textContent).not.toContain('conversation_deleted');
  });
});

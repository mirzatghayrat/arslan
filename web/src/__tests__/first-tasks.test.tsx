import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { useArslanStore, initialArslanState } from '../stores/arslanStore';
import { recordFirstTasks, readFirstTasks } from '../lib/firstRun';

/**
 * 0.1.60 first run (spec §2): after the film, the empty conversation offers a first thing to try for
 * each thing that was turned on. A click fills the box and never sends; the chips go after the
 * first message or when hidden.
 */
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: 'en' } }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const base = {
  chatHistory: [], setChatHistory: vi.fn(), spawns: [] as never[], currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(), activeThread: null,
};

beforeEach(() => {
  localStorage.clear();
  useArslanStore.setState(initialArslanState(), true);
});

describe('first things to try', () => {
  it('nothing recorded: no chips', () => {
    render(<OrchestratorChat {...base} onSendMessage={vi.fn()} />);
    expect(screen.queryByTestId('first-tasks')).toBeNull();
  });

  it('shows one chip per thing turned on, plus the web one, even when recorded after the chat opened', () => {
    render(<OrchestratorChat {...base} onSendMessage={vi.fn()} />);
    act(() => recordFirstTasks({ folders: true, hands: false }));
    expect(screen.getByTestId('first-task-tryFolders')).toBeInTheDocument();
    expect(screen.queryByTestId('first-task-tryHands')).toBeNull();
    expect(screen.getByTestId('first-task-tryWeb')).toBeInTheDocument();
  });

  it('a click fills the box and does not send', () => {
    recordFirstTasks({ folders: false, hands: true });
    const onSendMessage = vi.fn();
    render(<OrchestratorChat {...base} onSendMessage={onSendMessage} />);
    fireEvent.click(screen.getByTestId('first-task-tryHands'));
    expect((document.getElementById('landing-message-input') as HTMLTextAreaElement).value).toBe('firstRun.tryHands');
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('hiding them forgets them; so does the first message', () => {
    recordFirstTasks({ folders: true, hands: true });
    const first = render(<OrchestratorChat {...base} onSendMessage={vi.fn()} />);
    fireEvent.click(screen.getByTestId('first-tasks-hide'));
    expect(screen.queryByTestId('first-tasks')).toBeNull();
    expect(readFirstTasks()).toBeNull();
    first.unmount();

    recordFirstTasks({ folders: true, hands: true });
    const onSendMessage = vi.fn();
    render(<OrchestratorChat {...base} onSendMessage={onSendMessage} />);
    fireEvent.click(screen.getByTestId('first-task-tryFolders'));
    fireEvent.keyDown(document.getElementById('landing-message-input')!, { key: 'Enter' });
    expect(onSendMessage).toHaveBeenCalled();
    expect(screen.queryByTestId('first-tasks')).toBeNull();
    expect(readFirstTasks()).toBeNull();
  });
});

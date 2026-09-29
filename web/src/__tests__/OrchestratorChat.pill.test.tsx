import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import { useArslanStore } from '../stores/arslanStore';
import type { Message } from '../types';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];
const spawns = [{ id: '3', name: 'Research Analyst', domain: 'research', avatarEmoji: '🔬', status: 'idle' }] as never[];
const base = {
  chatHistory: history, setChatHistory: vi.fn(), spawns, currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(), activeThread: null, onSendMessage: vi.fn(),
};

function setStore(running: boolean) {
  useArslanStore.setState({
    roster: [{ spawnId: 3, spawnName: 'Research Analyst', joinedVia: 'invite', status: 'idle' }],
    pendingRoute: running ? { spawnId: 3, spawnName: 'Research Analyst' } : null,
    streamSpawnId: null,
  } as never);
}

// 0.1.44 one Arslan: no standing expert bar, even when an older conversation still
// has a roster member (or one is "running").
describe('OrchestratorChat expert bar is gone', () => {
  it.each([true, false])('renders no expert bar or pill (running=%s)', (running) => {
    setStore(running);
    const { container } = render(<OrchestratorChat {...base} />);
    expect(screen.queryByTestId('conversation-experts-bar')).toBeNull();
    expect(screen.queryByText('Research Analyst')).toBeNull();
    expect(container.querySelector('.shiny-text')).toBeNull();
  });
});

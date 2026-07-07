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

describe('OrchestratorChat spawn pill shimmer', () => {
  it('applies shiny-text to a running spawn pill label (pendingRoute matches)', () => {
    setStore(true);
    const { container } = render(<OrchestratorChat {...base} />);
    expect(container.querySelector('.shiny-text')?.textContent).toBe('Research Analyst');
  });

  it('no shimmer when idle — pill still renders, just without shiny-text', () => {
    setStore(false);
    const { container } = render(<OrchestratorChat {...base} />);
    expect(container.querySelector('.shiny-text')).toBeNull();
    expect(screen.getByText('Research Analyst')).toBeTruthy();
  });
});

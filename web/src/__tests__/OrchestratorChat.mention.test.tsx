import { render, screen, fireEvent } from '@testing-library/react';
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
const base = {
  chatHistory: history, setChatHistory: vi.fn(), spawns: [],
  currentStyle: 'quartz' as const, setCurrentStyle: vi.fn(), activeThread: null,
};

function withRoster() {
  useArslanStore.setState({ roster: [
    { spawnId: 3, spawnName: 'Deck Master', joinedVia: 'invite', status: 'idle' },
    { spawnId: 5, spawnName: 'Data Analyst', joinedVia: 'invite', status: 'idle' },
  ] } as never);
}

describe('OrchestratorChat @-mention autocomplete', () => {
  it('typing @ opens a roster dropdown filtered by the query', () => {
    withRoster();
    render(<OrchestratorChat {...base} onSendMessage={vi.fn()} />);
    const input = screen.getByPlaceholderText(/placeholder_chat/i);
    fireEvent.change(input, { target: { value: '@d' } });
    expect(screen.getByTestId('mention-dropdown')).toBeTruthy();
    // both start with 'd' → both listed
    expect(screen.getByText('Deck Master')).toBeTruthy();
    expect(screen.getByText('Data Analyst')).toBeTruthy();
    // narrow to 'de' → only Deck Master
    fireEvent.change(input, { target: { value: '@de' } });
    expect(screen.getByText('Deck Master')).toBeTruthy();
    expect(screen.queryByText('Data Analyst')).toBeNull();
  });

  it('clicking a candidate inserts the full @Name and closes the dropdown', () => {
    withRoster();
    render(<OrchestratorChat {...base} onSendMessage={vi.fn()} />);
    const input = screen.getByPlaceholderText(/placeholder_chat/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'hi @de' } });
    fireEvent.mouseDown(screen.getByText('Deck Master'));
    expect(input.value).toBe('hi @Deck Master ');
    expect(screen.queryByTestId('mention-dropdown')).toBeNull();
  });

  it('Enter selects the highlighted candidate instead of sending', () => {
    const spy = vi.fn();
    withRoster();
    render(<OrchestratorChat {...base} onSendMessage={spy} />);
    const input = screen.getByPlaceholderText(/placeholder_chat/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '@d' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input.value).toBe('@Deck Master ');
    expect(spy).not.toHaveBeenCalled();
  });

  it('Escape closes the dropdown', () => {
    withRoster();
    render(<OrchestratorChat {...base} onSendMessage={vi.fn()} />);
    const input = screen.getByPlaceholderText(/placeholder_chat/i);
    fireEvent.change(input, { target: { value: '@d' } });
    expect(screen.getByTestId('mention-dropdown')).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByTestId('mention-dropdown')).toBeNull();
  });
});

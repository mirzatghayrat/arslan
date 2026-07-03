import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import type { Message } from '../types';

// Deterministic i18n
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

vi.mock('../api/client', () => ({
  api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() },
}));

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];

describe('composer shell-policy pill', () => {
  it('is hidden when shell is disabled', () => {
    render(
      <OrchestratorChat
        chatHistory={history}
        setChatHistory={vi.fn()}
        onSendMessage={vi.fn()}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={vi.fn()}
        activeThread={null}
        shellEnabled={false}
      />,
    );
    expect(screen.queryByTestId('shell-policy-pill')).not.toBeInTheDocument();
  });

  it('renders the current policy and calls onShellPolicyChange on change', () => {
    const onChange = vi.fn();
    render(
      <OrchestratorChat
        chatHistory={history}
        setChatHistory={vi.fn()}
        onSendMessage={vi.fn()}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={vi.fn()}
        activeThread={null}
        shellEnabled={true}
        shellPolicy="ask_all"
        onShellPolicyChange={onChange}
      />,
    );
    const select = screen.getByTestId('shell-policy-select') as HTMLSelectElement;
    expect(select.value).toBe('ask_all');
    fireEvent.change(select, { target: { value: 'ask_risky' } });
    expect(onChange).toHaveBeenCalledWith('ask_risky');
  });
});

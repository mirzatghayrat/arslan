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
    const options = screen.getByTestId('execution-options') as HTMLDetailsElement;
    expect(options.open).toBe(false);
    expect(options.querySelector('summary')).toHaveTextContent('workspace.confirmCommands');
    fireEvent.click(options.querySelector('summary')!);
    expect(options.open).toBe(true);
    expect(select.value).toBe('ask_all');
    fireEvent.change(select, { target: { value: 'ask_risky' } });
    expect(onChange).toHaveBeenCalledWith('ask_risky');
  });

  it('keeps automatic read-only execution visible while advanced controls are closed', () => {
    render(<OrchestratorChat chatHistory={history} setChatHistory={vi.fn()} onSendMessage={vi.fn()}
      spawns={[]} currentStyle="linear" setCurrentStyle={vi.fn()} activeThread={null}
      shellEnabled shellPolicy="ask_risky" />);
    const options = screen.getByTestId('execution-options') as HTMLDetailsElement;
    expect(options.open).toBe(false);
    expect(options.querySelector('summary')).toHaveTextContent('workspace.readOnlyAutomatic');
    expect(screen.queryByText('orchestrator.footer_sandboxed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('conversation-experts-bar')).not.toBeInTheDocument();
    expect(screen.getByTestId('composer-input-tools').querySelectorAll('button').length).toBeGreaterThanOrEqual(2);
  });
});

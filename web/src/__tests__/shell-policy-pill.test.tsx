import { render, screen } from '@testing-library/react';
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

function chat(props: { shellEnabled: boolean; shellPolicy?: 'ask_all' | 'ask_risky' }) {
  return render(<OrchestratorChat chatHistory={history} setChatHistory={vi.fn()} onSendMessage={vi.fn()}
    spawns={[]} currentStyle="linear" setCurrentStyle={vi.fn()} activeThread={null} {...props} />);
}

// 0.1.42: the command-confirmation control moved to Settings → Advanced.
describe('composer execution posture', () => {
  it('shows nothing when shell is disabled', () => {
    chat({ shellEnabled: false });
    expect(screen.queryByTestId('execution-options')).not.toBeInTheDocument();
  });

  it('shows nothing under the default (0.1.48: ask only for risky commands)', () => {
    chat({ shellEnabled: true, shellPolicy: 'ask_risky' });
    expect(screen.queryByTestId('execution-options')).not.toBeInTheDocument();
    expect(screen.queryByTestId('shell-policy-select')).not.toBeInTheDocument();
  });

  it('says "every command asks" as one line when the user chose that, with no control in the composer', () => {
    chat({ shellEnabled: true, shellPolicy: 'ask_all' });
    expect(screen.getByTestId('execution-options')).toHaveTextContent('workspace.confirmCommands');
    expect(screen.queryByTestId('shell-policy-select')).not.toBeInTheDocument();
    expect(screen.queryByTestId('conversation-experts-bar')).not.toBeInTheDocument();
    expect(screen.getByTestId('composer-input-tools').querySelectorAll('button').length).toBeGreaterThanOrEqual(2);
  });
});

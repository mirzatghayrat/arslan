import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import type { Message } from '../types';
import { DEFAULT_SETTINGS } from '../data';

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

  it('shows nothing under the default (v0.1.63: ask before every command)', () => {
    chat({ shellEnabled: true, shellPolicy: 'ask_all' });
    expect(screen.queryByTestId('execution-options')).not.toBeInTheDocument();
    expect(screen.queryByTestId('shell-policy-select')).not.toBeInTheDocument();
  });

  it('marks the looser "ask only for risky commands" as one line when the user chose it, with no control in the composer', () => {
    chat({ shellEnabled: true, shellPolicy: 'ask_risky' });
    expect(screen.getByTestId('execution-options')).toHaveTextContent('workspace.readOnlyAutomatic');
    expect(screen.queryByTestId('shell-policy-select')).not.toBeInTheDocument();
    expect(screen.queryByTestId('conversation-experts-bar')).not.toBeInTheDocument();
    expect(screen.getByTestId('composer-input-tools').querySelectorAll('button').length).toBeGreaterThanOrEqual(2);
  });

  it('the app starts on asking before every command until the server says otherwise', () => {
    expect(DEFAULT_SETTINGS.shellConfirmPolicy).toBe('ask_all');
  });
});

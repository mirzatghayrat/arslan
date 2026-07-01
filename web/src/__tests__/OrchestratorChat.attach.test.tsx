import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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

// A non-empty history so the footer composer (with AttachBar) renders.
const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];

describe('OrchestratorChat attach', () => {
  it('sends (text, { context, names }) when an attachment is present', async () => {
    const { api } = await import('../api/client');
    (api.extractAttachmentUrl as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: 'DOC BODY', chars: 8, truncated: false,
    });
    const spy = vi.fn();
    render(
      <OrchestratorChat
        chatHistory={history}
        setChatHistory={vi.fn()}
        onSendMessage={spy}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={vi.fn()}
        activeThread={null}
      />,
    );
    // Paste a URL straight into the composer → auto-extract via the SSRF-hardened path (no button)
    const msgInput = screen.getByPlaceholderText(/placeholder_chat/i);
    fireEvent.paste(msgInput, { clipboardData: { files: [], getData: () => 'https://x.com' } });
    await screen.findByLabelText('remove-attachment');
    fireEvent.change(msgInput, { target: { value: 'summarise' } });
    const form = msgInput.closest('form');
    if (form) fireEvent.submit(form);
    await waitFor(() => expect(spy).toHaveBeenCalledWith('summarise', {
      context: 'DOC BODY',
      names: ['https://x.com'],
    }));
  });

  it('sends (text, undefined) when no attachment is present', () => {
    const spy = vi.fn();
    render(
      <OrchestratorChat
        chatHistory={history}
        setChatHistory={vi.fn()}
        onSendMessage={spy}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={vi.fn()}
        activeThread={null}
      />,
    );
    const msgInput = screen.getByPlaceholderText(/placeholder_chat/i);
    fireEvent.change(msgInput, { target: { value: 'hello' } });
    const form = msgInput.closest('form');
    if (form) fireEvent.submit(form);
    expect(spy).toHaveBeenCalledWith('hello', undefined);
  });
});

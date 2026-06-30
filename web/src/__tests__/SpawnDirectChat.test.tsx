import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeAll } from 'vitest'
import SpawnDirectChat from '../components/SpawnDirectChat'

// Mock i18n so the component renders deterministically
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

let frameCb: (m: any) => void = () => {};
const sendSpy = vi.fn();
vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: (_path: string, onMessage: (m: any) => void) => {
    frameCb = onMessage;
    return { send: sendSpy, reconnecting: false, setLastMessageId: vi.fn() };
  },
}));

vi.mock('../api/client', () => ({
  api: {
    extractAttachmentUrl: vi.fn(),
    extractAttachmentFile: vi.fn(),
  },
}));

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

const mockSpawn = {
  id: '7',
  name: '小美',
  avatarEmoji: '🌸',
  domain: 'Test',
  description: 'Test spawn',
  status: 'idle' as const,
  tools: [],
  skills: [],
  totalTasks: 0,
};

describe('SpawnDirectChat', () => {
  it('renders history messages', async () => {
    render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);
    act(() => {
      frameCb({ type: 'history', messages: [
        { message_id: 1, role: 'user', content: 'hi' },
        { message_id: 2, role: 'assistant', content: '你好!' },
      ]});
    });
    expect(screen.getByText('你好!')).toBeTruthy();
  });

  it('sends a real WS frame on submit', async () => {
    sendSpy.mockClear();
    render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);
    // Find the message input (not the URL input in AttachBar)
    const input = screen.getByPlaceholderText(/spawn_chat/i);
    fireEvent.change(input, { target: { value: 'hi' } });
    const form = input.closest('form');
    if (form) {
      fireEvent.submit(form);
    } else {
      // try button click
      const btn = screen.getByRole('button');
      fireEvent.click(btn);
    }
    expect(sendSpy).toHaveBeenCalledWith({ type: 'user_message', content: 'hi' });
  });

  it('renders streaming chunks combined', async () => {
    render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);
    act(() => { frameCb({ type: 'stream_start', message_id: 0 }); });
    act(() => { frameCb({ type: 'stream_chunk', content: '部分' }); });
    act(() => { frameCb({ type: 'stream_chunk', content: '回复' }); });
    act(() => { frameCb({ type: 'stream_end', message_id: 9 }); });
    expect(screen.getByText('部分回复')).toBeTruthy();
  });

  it('sends attached_context + attached_names with the message', async () => {
    const { api } = await import('../api/client');
    (api.extractAttachmentUrl as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: 'DOC BODY', chars: 8, truncated: false,
    });
    sendSpy.mockClear();
    render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);
    // Reveal the URL field from the "+" menu, then extract via the SSRF-hardened path
    fireEvent.click(screen.getByLabelText('attach.url'));
    fireEvent.change(screen.getByPlaceholderText('attach.url_placeholder'), { target: { value: 'https://x.com' } });
    fireEvent.click(screen.getByText('attach.read'));
    await screen.findByLabelText('remove-attachment');  // chip present
    // type message in the message input (different placeholder from url input)
    const msgInput = screen.getByPlaceholderText(/spawn_chat/i);
    fireEvent.change(msgInput, { target: { value: 'summarise' } });
    const form = msgInput.closest('form');
    if (form) fireEvent.submit(form);
    await waitFor(() => expect(sendSpy).toHaveBeenCalledWith(expect.objectContaining({
      type: 'user_message',
      content: 'summarise',
      attached_context: 'DOC BODY',
      attached_names: ['https://x.com'],
    })));
  });

  it('renders an attachment_stored system note', () => {
    render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);
    act(() => frameCb({ type: 'attachment_stored', spawn_name: '小美', chunks: 3 }));
    expect(screen.getByText(/已记入.*小美|记入.*小美/)).toBeInTheDocument();
  });

  it('REGRESSION: no fabricated tool activity after real reply', async () => {
    sendSpy.mockClear();
    render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);
    const input = screen.getByPlaceholderText(/spawn_chat/i);
    fireEvent.change(input, { target: { value: 'hi' } });
    const form = input.closest('form');
    if (form) fireEvent.submit(form);
    act(() => { frameCb({ type: 'stream_start', message_id: 0 }); });
    act(() => { frameCb({ type: 'stream_chunk', content: '你好' }); });
    act(() => { frameCb({ type: 'stream_end', message_id: 10 }); });
    expect(screen.queryByText(/Web Search/i)).toBeNull();
    expect(screen.queryByText(/Sandbox task executed/i)).toBeNull();
  });
});

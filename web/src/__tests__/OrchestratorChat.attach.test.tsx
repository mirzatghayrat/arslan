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
  it('restores prepared source and text after settings-style unmount, then sends them together', async () => {
    const { api } = await import('../api/client');
    vi.mocked(api.extractAttachmentFile).mockResolvedValue({ text: 'ready source', chars: 12, truncated: true });
    const spy = vi.fn();
    const props = { chatHistory: history, setChatHistory: vi.fn(), onSendMessage: spy,
      spawns: [], currentStyle: 'quartz' as const, setCurrentStyle: vi.fn(), activeThread: null, conversationId: 'settings-attachment' };
    const first = render(<OrchestratorChat {...props} />);
    fireEvent.change(first.container.querySelector('input[type="file"]')!, { target: { files: [new File(['source'], 'draft.txt', { type: 'text/plain' })] } });
    await screen.findByLabelText('ui.removeAttachment');
    fireEvent.change(screen.getByPlaceholderText(/placeholder_chat/i), { target: { value: 'keep my draft' } });
    first.unmount();
    render(<OrchestratorChat {...props} />);
    expect(screen.getByLabelText('ui.removeAttachment')).toBeInTheDocument();
    const input = screen.getByPlaceholderText(/placeholder_chat/i);
    expect(input).toHaveValue('keep my draft');
    fireEvent.submit(input.closest('form')!);
    expect(spy).toHaveBeenCalledWith('keep my draft', expect.objectContaining({
      names: ['draft.txt'], context: '["draft.txt": attach.delivery_truncated]\nready source',
    }));
    expect(screen.queryByLabelText('ui.removeAttachment')).not.toBeInTheDocument();
  });

  it.each([['excerpt', true, 'truncated'], ['', false, 'empty']] as const)(
    'sends extraction limitations (%s) with the attachment',
    async (text, truncated, status) => {
      const { api } = await import('../api/client');
      vi.mocked(api.extractAttachmentUrl).mockResolvedValue({ text, chars: text.length, truncated });
      const spy = vi.fn();
      render(<OrchestratorChat chatHistory={history} setChatHistory={vi.fn()} onSendMessage={spy} spawns={[]} currentStyle="quartz" setCurrentStyle={vi.fn()} activeThread={null} />);
      const input = screen.getByPlaceholderText(/placeholder_chat/i);
      fireEvent.paste(input, { clipboardData: { files: [], getData: () => 'https://x.com' } });
      await screen.findByLabelText('ui.removeAttachment');
      fireEvent.change(input, { target: { value: 'summarise' } });
      fireEvent.submit(input.closest('form')!);
      expect(spy).toHaveBeenCalledWith('summarise', expect.objectContaining({
        context: '["https://x.com": attach.delivery_' + status + ']\n' + text,
        names: ['https://x.com'],
        display: [expect.objectContaining({ extractionStatus: status })],
      }));
    },
  );
  it('sends sampled video frames with their source locators through the real image payload path', async () => {
    const { api } = await import('../api/client');
    const images = [{ name: 'clip.mp4#t=1.000s', source_locator: 'clip.mp4#t=1.000s', mime_type: 'image/png', data: 'cG5n' }];
    vi.mocked(api.extractAttachmentFile).mockResolvedValue({ text: 'video metadata and locators', chars: 27, truncated: false, images, video_frame_status: 'sampled' });
    const spy = vi.fn();
    const { container } = render(<OrchestratorChat chatHistory={history} setChatHistory={vi.fn()} onSendMessage={spy}
      spawns={[]} currentStyle="quartz" setCurrentStyle={vi.fn()} activeThread={null} />);
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(['clip'], 'clip.mp4', { type: 'video/mp4' })] } });
    await screen.findByText(/inputs.videoSamples/);
    const input = screen.getByPlaceholderText(/placeholder_chat/i);
    fireEvent.change(input, { target: { value: 'describe the middle frame' } });
    fireEvent.submit(input.closest('form')!);
    expect(spy).toHaveBeenCalledWith('describe the middle frame', expect.objectContaining({ images, names: ['clip.mp4'] }));
  });

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
    await screen.findByLabelText('ui.removeAttachment');
    fireEvent.change(msgInput, { target: { value: 'summarise' } });
    const form = msgInput.closest('form');
    if (form) fireEvent.submit(form);
    await waitFor(() => expect(spy).toHaveBeenCalledWith('summarise', {
      context: 'DOC BODY',
      names: ['https://x.com'],
      // display echoes ALL attachments for the sent bubble (session-only)
      display: [{ name: 'https://x.com', kind: 'doc', previewUrl: undefined }],
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

describe('OrchestratorChat hero attach (empty state)', () => {
  const base = {
    setChatHistory: vi.fn(),
    spawns: [],
    currentStyle: 'quartz' as const,
    setCurrentStyle: vi.fn(),
    activeThread: null,
  };

  it('the empty-state hero exposes an attach control (＋)', () => {
    render(<OrchestratorChat {...base} chatHistory={[]} onSendMessage={vi.fn()} />);
    // hero input is present …
    expect(screen.getByPlaceholderText(/placeholder_empty/i)).toBeTruthy();
    // … and now so is the attach button (was missing before)
    expect(screen.getByLabelText('attach.add')).toBeTruthy();
  });

  it('hero: a pasted url attaches and rides into context on send', async () => {
    const { api } = await import('../api/client');
    (api.extractAttachmentUrl as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: 'DOC BODY', chars: 8, truncated: false,
    });
    const spy = vi.fn();
    render(<OrchestratorChat {...base} chatHistory={[]} onSendMessage={spy} />);
    const heroInput = screen.getByPlaceholderText(/placeholder_empty/i);
    fireEvent.paste(heroInput, { clipboardData: { files: [], getData: () => 'https://x.com' } });
    await screen.findByLabelText('ui.removeAttachment');
    fireEvent.change(heroInput, { target: { value: 'summarise' } });
    fireEvent.keyDown(heroInput, { key: 'Enter' });   // hero sends via Enter (no <form>)
    await waitFor(() => expect(spy).toHaveBeenCalledWith('summarise', {
      context: 'DOC BODY',
      names: ['https://x.com'],
      display: [{ name: 'https://x.com', kind: 'doc', previewUrl: undefined }],
    }));
  });
});

describe('sent user bubble attachments', () => {
  const base = {
    chatHistory: [] as Message[],
    setChatHistory: vi.fn(),
    onSendMessage: vi.fn(),
    spawns: [],
    currentStyle: 'quartz' as const,
    setCurrentStyle: vi.fn(),
    activeThread: null,
  };

  it('renders an <img> thumbnail from the previewUrl for a sent image attachment', () => {
    const history: Message[] = [
      { id: 'a1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
      {
        id: 'u1', sender: 'user', senderName: 'You', senderAvatar: '🦁', text: 'look at this', timestamp: '10:01',
        attachments: [{ name: 'photo.png', kind: 'image', previewUrl: 'blob:mock-url' }],
      },
    ];
    render(<OrchestratorChat {...base} chatHistory={history} />);
    const img = screen.getByAltText('photo.png') as HTMLImageElement;
    expect(img.tagName).toBe('IMG');
    expect(img.getAttribute('src')).toBe('blob:mock-url');
  });

  it('history-restored image (no previewUrl — object-URLs die on reload) falls back to a chip, no <img>', () => {
    const history: Message[] = [
      { id: 'a1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
      {
        id: 'u1', sender: 'user', senderName: 'You', senderAvatar: '🦁', text: 'look at this', timestamp: '10:01',
        attachments: [{ name: 'photo.png', kind: 'image' }],
      },
    ];
    render(<OrchestratorChat {...base} chatHistory={history} />);
    expect(screen.queryByAltText('photo.png')).toBeNull();
    // compact file-chip fallback shows the name — honest, no broken-image icon
    expect(screen.getByText('photo.png')).toBeTruthy();
  });

  it('doc attachments render as compact chips (name), never as <img>', () => {
    const history: Message[] = [
      { id: 'a1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
      {
        id: 'u1', sender: 'user', senderName: 'You', senderAvatar: '🦁', text: 'summarise', timestamp: '10:01',
        attachments: [{ name: 'notes.pdf', kind: 'doc' }],
      },
    ];
    render(<OrchestratorChat {...base} chatHistory={history} />);
    expect(screen.getByText('notes.pdf')).toBeTruthy();
    expect(screen.queryByAltText('notes.pdf')).toBeNull();
  });

  it('user message without attachments renders no attachment block at all', () => {
    const history: Message[] = [
      { id: 'a1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
      { id: 'u1', sender: 'user', senderName: 'You', senderAvatar: '🦁', text: 'plain text', timestamp: '10:01' },
    ];
    const { container } = render(<OrchestratorChat {...base} chatHistory={history} />);
    expect(container.querySelector('.sent-attachments')).toBeNull();
  });
});

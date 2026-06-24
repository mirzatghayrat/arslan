import { render, screen, fireEvent, act } from '@testing-library/react'
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
    // Find the input
    const input = screen.getByPlaceholderText(/./);
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

  it('REGRESSION: no fabricated tool activity after real reply', async () => {
    sendSpy.mockClear();
    render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);
    const input = screen.getByPlaceholderText(/./);
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

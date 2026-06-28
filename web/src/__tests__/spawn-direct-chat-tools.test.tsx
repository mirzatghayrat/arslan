import { render, screen, act } from '@testing-library/react'
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

describe('SpawnDirectChat tool frames + artifact', () => {
  it('accumulates tool frames and renders the chart artifact', () => {
    const { container } = render(<SpawnDirectChat spawn={mockSpawn} currentStyle="quartz" />);

    act(() => { frameCb({ type: 'stream_start', message_id: 0 }); });
    act(() => { frameCb({ type: 'tool_call', tool: 'web_search', args_summary: '{"query":"AAPL"}' }); });
    act(() => { frameCb({ type: 'tool_result', tool: 'web_search', ok: true, summary: 'found 5 results', artifact: null }); });
    act(() => { frameCb({ type: 'tool_call', tool: 'render_chart', args_summary: '{}' }); });
    act(() => { frameCb({ type: 'tool_result', tool: 'render_chart', ok: true, summary: 'chart rendered', artifact: { kind: 'svg', content: "<svg id='c'/>" } }); });
    act(() => { frameCb({ type: 'stream_chunk', content: 'done' }); });
    act(() => { frameCb({ type: 'stream_end', message_id: 42 }); });

    // The streamed reply text shows
    expect(screen.getByText('done')).toBeTruthy();

    // The chart svg got injected into the DOM
    const svg = container.querySelector('.tool-chart svg#c');
    expect(svg).toBeTruthy();

    // tool result summaries surfaced in the tool activity panel
    expect(screen.getByText(/chart rendered/)).toBeTruthy();
  });
});

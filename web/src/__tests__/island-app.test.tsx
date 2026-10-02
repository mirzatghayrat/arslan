import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IslandApp, { elapsed, pollDelay } from '../island/IslandApp';
import { initialState } from '../island/islandMachine';
import { pickLang, stepText } from '../locales/island';

const feedBody = (over: Record<string, unknown> = {}) => ({
  cursor: 3, awaiting: 0, awaiting_conversations: [], events: [], enabled: true,
  active: [{
    id: 1, conversation_id: 'c1', kind: 'job', title: 'Find 10 jobs in Shanghai', started_at: 1,
    step: { tool: 'web_search', target: 'product manager shanghai', at: 2 },
    plan: { items: [{ text: 'find sources', status: 'done' }, { text: 'collect', status: 'in_progress' },
                    { text: 'save', status: 'pending' }], done: 1, total: 3 },
  }],
  ...over,
});

beforeEach(() => {
  vi.useFakeTimers();
  if (!window.requestAnimationFrame) {
    (window as unknown as { requestAnimationFrame: unknown }).requestAnimationFrame = (cb: FrameRequestCallback) => setTimeout(() => cb(performance.now()), 16) as unknown as number;
    (window as unknown as { cancelAnimationFrame: unknown }).cancelAnimationFrame = (id: number) => clearTimeout(id);
  }
  localStorage.setItem('i18nextLng', 'en');
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); localStorage.clear(); });

async function mount(body: Record<string, unknown>) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  render(<IslandApp />);
  await act(async () => { await vi.advanceTimersByTimeAsync(10); });
  return fetchMock;
}

describe('island page', () => {
  it('reads the feed with the token and shows a strip with the plan count while work runs', async () => {
    (window as unknown as { __ARSLAN_TOKEN__?: string }).__ARSLAN_TOKEN__ = 'tok';
    const fetchMock = await mount(feedBody());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/island/feed?after=0');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island.dataset.mode).toBe('compact');
    expect(island).toHaveTextContent('1/3');
    delete (window as unknown as { __ARSLAN_TOKEN__?: string }).__ARSLAN_TOKEN__;
  });

  it('hover opens the overview: title, plan and the current step in words', async () => {
    await mount(feedBody());
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    fireEvent.mouseEnter(island);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(island.dataset.mode).toBe('expanded');
    expect(island).toHaveTextContent('Find 10 jobs in Shanghai');
    expect(island).toHaveTextContent('✓ find sources');
    expect(island).toHaveTextContent('Search “product manager shanghai”');
  });

  it('a waiting card opens by itself with a way to approve in the app', async () => {
    await mount(feedBody({ awaiting: 1, awaiting_conversations: ['c1'],
      active: [{ ...feedBody().active[0], step: { tool: 'run_command', target: 'rm -rf ~/Downloads/old', at: 3 } }] }));
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island.dataset.mode).toBe('expanded');
    expect(island).toHaveTextContent('Waiting for you');
    expect(island).toHaveTextContent('Run rm -rf ~/Downloads/old');
    expect(screen.getByRole('button', { name: 'Open to approve' })).toBeInTheDocument();
    expect(island.querySelector('.mascot[data-state="approval"]')).not.toBeNull();
  });

  it('renders nothing when turned off in Settings', async () => {
    await mount(feedBody({ enabled: false }));
    expect(screen.queryByRole('region')).toBeNull();
  });

  it('follows the app language', async () => {
    localStorage.setItem('i18nextLng', 'zh');
    await mount(feedBody());
    fireEvent.mouseEnter(screen.getByRole('region'));
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(screen.getByRole('region')).toHaveTextContent('搜索「product manager shanghai」');
  });
});

describe('island helpers', () => {
  it('polls briskly only while something is happening', () => {
    const s = initialState();
    expect(pollDelay(s, false)).toBe(2500);
    expect(pollDelay({ ...s, awaiting: 1 }, false)).toBe(1000);
    expect(pollDelay({ ...s, enabled: false }, false)).toBe(5000);
    expect(pollDelay(s, true)).toBe(3000);
  });

  it('formats elapsed time and picks a supported language', () => {
    expect(elapsed(83)).toBe('1:23');
    expect(elapsed(3723)).toBe('1:02:03');
    expect(pickLang('zh-CN', 'en')).toBe('zh');
    expect(pickLang(null, 'fr-CA')).toBe('fr');
    expect(pickLang('xx', 'yy')).toBe('en');
  });

  it('puts steps in words and never invents a target', () => {
    expect(stepText('en', 'write_file', 'jobs.csv')).toBe('Write jobs.csv');
    expect(stepText('en', 'update_plan', null)).toBe('Update the plan');
    expect(stepText('en', 'web_extract', null)).toBe('Use web extract');
    expect(stepText('en', 'mcp_github_search', 'x')).toBe('Use mcp github search');
  });
});

/** 0.1.55 Island v2: answer a waiting card in the island (decision 3), Stop a job, Open Arslan. */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IslandApp from '../island/IslandApp';
import { askKind, askLine, mmss, secondsLeft } from '../island/islandAsk';
import type { PendingCard } from '../island/feed';

const job = { id: 1, conversation_id: 'c1', kind: 'job', title: 'Collect postings', started_at: 1, step: null, plan: null, job_id: 'job-7' };
const feed = (over: Record<string, unknown> = {}) => ({ cursor: 3, awaiting: 0, awaiting_conversations: [], events: [], enabled: true, active: [job], ...over });
const card = (over: Partial<PendingCard> & { frame: PendingCard['frame'] }): PendingCard => ({
  call_id: 'k1', conversation_id: 'c1', opened_at: 1000, expires_at: 1300, island_ok: true, ...over,
});

let calls: { url: string; init?: RequestInit }[] = [];
function serve(routes: { feed: unknown; pending?: unknown; answer?: number }) {
  calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.startsWith('/api/v1/island/feed')) return new Response(JSON.stringify(routes.feed), { status: 200 });
    if (url === '/api/v1/approvals/pending') return new Response(JSON.stringify(routes.pending ?? []), { status: 200 });
    if (url.includes('/answer')) return new Response('{}', { status: routes.answer ?? 200 });
    return new Response('{"ok":true}', { status: 200 });
  }));
}
const posted = (part: string) => calls.filter((c) => c.url.includes(part) && c.init?.method === 'POST');

beforeEach(() => { vi.useFakeTimers(); localStorage.setItem('i18nextLng', 'en'); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); localStorage.clear(); });

async function mount() {
  render(<IslandApp />);
  await act(async () => { await vi.advanceTimersByTimeAsync(20); });
}

describe('answering in the island', () => {
  it('a card the server allows here: Allow answers it with source island', async () => {
    serve({ feed: feed({ awaiting: 1, awaiting_conversations: ['c1'] }),
      pending: [card({ call_id: 'c9', frame: { type: 'propose_run_command', pretty: 'git status' } })] });
    await mount();
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island).toHaveTextContent('Run a command');
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('git status');
    expect(screen.queryByTestId('island-risky')).toBeNull();
    await act(async () => { fireEvent.click(screen.getByTestId('island-allow')); await vi.advanceTimersByTimeAsync(10); });
    const [answer] = posted('/approvals/c9/answer');
    expect(JSON.parse(String(answer.init?.body))).toEqual({ approve: true, source: 'island' });
    expect(screen.queryByTestId('island-allow')).toBeNull();   // answered: the card leaves
  });

  it('a risky card cannot be allowed here: it says why, opens Arslan, and can still be declined', async () => {
    serve({ feed: feed({ awaiting: 1, awaiting_conversations: ['c1'] }),
      pending: [card({ call_id: 'r1', island_ok: false, frame: { type: 'propose_action', kind: 'desktop_risky', target: 'Mail · Send', detail: '' } })] });
    await mount();
    expect(screen.queryByTestId('island-allow')).toBeNull();
    expect(screen.getByTestId('island-risky')).toHaveTextContent('delete, send or pay');
    expect(screen.getByTestId('island-open-in-arslan')).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByTestId('island-decline')); await vi.advanceTimersByTimeAsync(10); });
    expect(JSON.parse(String(posted('/approvals/r1/answer')[0].init?.body))).toEqual({ approve: false, source: 'island' });
  });

  it('a refused answer says so and keeps the card', async () => {
    serve({ feed: feed({ awaiting: 1 }), answer: 403,
      pending: [card({ frame: { type: 'propose_schedule', name: 'Brief', when: 'every: 3600' } })] });
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId('island-allow')); await vi.advanceTimersByTimeAsync(10); });
    expect(screen.getByRole('alert')).toHaveTextContent('Open Arslan');
    expect(screen.getByTestId('island-allow')).toBeInTheDocument();
  });

  it('shows the queue when more than one waits', async () => {
    serve({ feed: feed({ awaiting: 2 }), pending: [
      card({ call_id: 'a', frame: { type: 'propose_schedule', name: 'A', when: 'every: 60' } }),
      card({ call_id: 'b', frame: { type: 'propose_schedule', name: 'B', when: 'every: 60' } })] });
    await mount();
    expect(screen.getByTestId('island-queue')).toHaveTextContent('1 / 2');
  });

  it('a malformed entry is skipped, not rendered as a broken card', async () => {
    serve({ feed: feed({ awaiting: 2 }), pending: [{ call_id: 'bad' },
      card({ call_id: 'ok', frame: { type: 'propose_schedule', name: 'Brief', when: 'every: 60' } })] });
    await mount();
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('Brief');
    expect(screen.queryByTestId('island-queue')).toBeNull();
  });

  it('no list yet (or an old server): the old "open to approve" card, never a broken one', async () => {
    serve({ feed: feed({ awaiting: 1, awaiting_conversations: ['c1'] }), pending: { not: 'a list' } });
    await mount();
    expect(screen.getByRole('button', { name: 'Open to approve' })).toBeInTheDocument();
  });
});

describe('the expanded overview', () => {
  it('shows elapsed time, Stop for a job, and Open Arslan', async () => {
    vi.setSystemTime(new Date(65_000));
    serve({ feed: feed() });
    await mount();
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    fireEvent.mouseEnter(island);
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    expect(screen.getByTestId('island-elapsed')).toHaveTextContent(/^1:0\d$/);
    expect(screen.getByTestId('island-open')).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByTestId('island-stop-job')); await vi.advanceTimersByTimeAsync(10); });
    expect(posted('/background-jobs/job-7/stop')).toHaveLength(1);
  });

  it('a turn (no job id) has no Stop', async () => {
    serve({ feed: feed({ active: [{ ...job, kind: 'turn', job_id: null }] }) });
    await mount();
    fireEvent.mouseEnter(screen.getByRole('region', { name: 'Arslan Island' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    expect(screen.queryByTestId('island-stop-job')).toBeNull();
  });
});

describe('what a card says', () => {
  it('names the exact thing for each kind', () => {
    expect(askKind(card({ frame: { type: 'propose_action', kind: 'mac_script' } }))).toBe('mac_script');
    expect(askKind(card({ frame: { type: 'propose_new_thing' } }))).toBe('other');
    expect(askLine(card({ frame: { type: 'propose_run_command', pretty: 'ls', remote_host: '192.168.1.8' } }))).toBe('192.168.1.8 · ls');
    expect(askLine(card({ frame: { type: 'propose_workspace_write', path: 'notes.md', workspace: '~/Arslan' } }))).toBe('notes.md');
    expect(askLine(card({ frame: { type: 'propose_schedule', name: 'Brief', when: 'cron: 0 9 * * *' } }))).toBe('Brief · cron: 0 9 * * *');
    expect(askLine(card({ frame: { type: 'propose_action', kind: 'mac_script', target: 'Notes', detail: '\n tell application "Notes"\nend tell' } })))
      .toBe('Notes · tell application "Notes"');
    expect(secondsLeft(card({ frame: { type: 'x' }, expires_at: 1300 }), 1_250_000)).toBe(50);
    expect(secondsLeft(card({ frame: { type: 'x' }, expires_at: 1300 }), 1_400_000)).toBe(0);
    expect(mmss(65)).toBe('1:05');
  });
});

describe('over a full-screen app', () => {
  it('a waiting card shows as a still tab with the time left; hover opens the card', async () => {
    (window as unknown as { __ARSLAN_ISLAND_GEOMETRY__?: unknown }).__ARSLAN_ISLAND_GEOMETRY__ =
      { notch: true, notchWidth: 188, barHeight: 32, fullscreen: true };
    vi.setSystemTime(new Date(1_000_000));
    serve({ feed: feed({ awaiting: 1 }), pending: [card({ expires_at: 1_000 + 272, frame: { type: 'propose_schedule', name: 'Brief', when: 'every: 60' } })] });
    await mount();
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island.dataset.mode).toBe('tab');
    expect(screen.getByTestId('island-tab')).toHaveTextContent(/Waiting for you\s*4:3\d/);
    expect(island.querySelector('.pulse-dot')).toBeNull();          // still: no pulsing
    fireEvent.mouseEnter(island);
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(island.dataset.mode).toBe('expanded');
    expect(screen.getByTestId('island-allow')).toBeInTheDocument();
    delete (window as unknown as { __ARSLAN_ISLAND_GEOMETRY__?: unknown }).__ARSLAN_ISLAND_GEOMETRY__;
  });
});

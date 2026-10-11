/**
 * Hands v2 on the island (spec §6.3-6.6, mock round 5): a borrow waiting for your pause and its
 * two answers, the front borrowed, the screen taken over with the time left and Stop, a paused
 * takeover with Stop / I'll do it / Continue, and the window being worked on as a thumbnail.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IslandApp from '../island/IslandApp';
import { applyFeed, dismiss, handsKey, initialState, mood } from '../island/islandMachine';
import type { Feed, HandsLine } from '../island/feed';
import { MESSAGES } from '../locales/island';

const activity = {
  id: 1, conversation_id: 'c1', kind: 'job', title: 'Set the font in Keynote', started_at: 1,
  step: { tool: 'desktop_select', target: 'Keynote · Font', at: 2 }, plan: null, job_id: 'j1',
};
const body = (hands: HandsLine | null, over: Record<string, unknown> = {}) => ({
  cursor: 3, awaiting: 0, awaiting_conversations: [], events: [], enabled: true, active: [activity], hands, ...over,
});
const feed = (hands: HandsLine | null): Feed => body(hands) as unknown as Feed;
const waiting: HandsLine = { borrow: 'waiting', takeover: null };
const paused: HandsLine = { borrow: null, takeover: { active: true, paused: true, remaining_s: 180 } };
const running: HandsLine = { borrow: null, takeover: { active: true, paused: false, remaining_s: 192 } };

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.setItem('i18nextLng', 'en');
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); localStorage.clear(); });

async function mount(feedBody: Record<string, unknown>) {
  const posted: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posted.push(url);
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    return new Response(JSON.stringify(feedBody), { status: 200 });
  }));
  render(<IslandApp />);
  await act(async () => { await vi.advanceTimersByTimeAsync(10); });
  return posted;
}

describe('island state for Hands', () => {
  it('a waiting borrow, a takeover and a paused takeover open the panel; a borrow and a takeover look working, a pause needs you', () => {
    for (const [hands, m] of [[waiting, 'working'], [running, 'working'], [paused, 'approval']] as const) {
      const s = applyFeed(applyFeed(initialState(), feed(null), 0), feed(hands), 1);
      expect([s.mode, s.view]).toEqual(['expanded', 'hands']);
      expect(mood(s)).toBe(m);
    }
  });

  const showing = (s: ReturnType<typeof initialState>) => s.mode === 'expanded' && s.view === 'hands';

  it('closed by hand it stays closed until the state changes', () => {
    let s = applyFeed(applyFeed(initialState(), feed(null), 0), feed(running), 1);
    s = dismiss(s, 2);
    expect(showing(s)).toBe(false);
    s = applyFeed(s, feed(running), 3);
    expect(showing(s)).toBe(false);
    s = applyFeed(s, feed(paused), 4);
    expect(showing(s)).toBe(true);
    expect(handsKey(s.hands)).toBe('paused');
  });

  it('nothing from Hands, nothing shown for it', () => {
    const s = applyFeed(applyFeed(initialState(), feed(null), 0), feed(null), 1);
    expect(showing(s)).toBe(false);
  });
});

describe('island page for Hands', () => {
  it('a waiting borrow says why it waits and answers now or not this time', async () => {
    const posted = await mount(body(waiting));
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island).toHaveTextContent('Waiting for you to pause, to borrow the front');
    expect(island).toHaveTextContent('Choose in Keynote · Font');
    fireEvent.click(screen.getByTestId('island-borrow-now'));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    fireEvent.click(screen.getByTestId('island-borrow-skip'));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(posted).toEqual(['/api/v1/hands/borrow/now', '/api/v1/hands/borrow/skip']);
  });

  it('a borrow that goes to another desktop says which app, waiting and while there', async () => {
    await mount(body({ borrow: 'waiting', desk: 'TextEdit', takeover: null }));
    let island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island).toHaveTextContent("Waiting for you to pause, to go to TextEdit's desktop");
    expect(island).toHaveTextContent('switches to the desktop where TextEdit is');
    expect(screen.getByTestId('island-borrow-now')).toBeInTheDocument();
    cleanup();
    await mount(body({ borrow: 'borrowing', desk: 'TextEdit', takeover: null }));
    island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island).toHaveTextContent('Working in TextEdit on another desktop');
    expect(island).not.toHaveTextContent('Waiting for you to pause');
  });

  it('a takeover shows the time left and Stop ends it', async () => {
    const posted = await mount(body(running));
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island).toHaveTextContent('Screen taken over');
    expect(island).toHaveTextContent('3:12');
    fireEvent.click(screen.getByTestId('island-takeover-stop'));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(posted).toEqual(['/api/v1/hands/takeover/end']);
  });

  it('a paused takeover offers Stop, I’ll do it and Continue', async () => {
    const posted = await mount(body(paused));
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island).toHaveTextContent('You moved, so it stopped');
    expect(island.querySelector('.mascot[data-state="approval"]')).not.toBeNull();
    fireEvent.click(screen.getByTestId('island-takeover-continue'));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(posted).toEqual(['/api/v1/hands/takeover/continue']);
    fireEvent.click(screen.getByTestId('island-takeover-me'));         // the work waits; the panel closes
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(posted).toEqual(['/api/v1/hands/takeover/continue']);
  });

  it('the window being worked on shows as a thumbnail in the overview', async () => {
    await mount(body(null, { active: [{ ...activity, thumb: 'AAAA' }] }));
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    fireEvent.mouseEnter(island);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    const thumb = screen.getByTestId('island-thumb') as HTMLImageElement;
    expect(thumb.src).toBe('data:image/jpeg;base64,AAAA');
    expect(thumb.alt).toBe('The window it is working in');
  });

  it('every Hands line exists in the six languages', () => {
    const keys = ['borrowWaiting', 'borrowWaitingText', 'borrowNow', 'borrowSkip', 'borrowing', 'borrowingText',
      'takeover', 'takeoverRunning', 'takeoverText', 'pausedTitle', 'pausedText', 'pausedMe', 'pausedContinue',
      'pausedMeNote', 'thumbAlt', 'deskWaiting', 'deskWaitingText', 'deskWorking', 'deskWorkingText'] as const;
    for (const lang of Object.keys(MESSAGES) as (keyof typeof MESSAGES)[]) {
      for (const key of keys) expect(MESSAGES[lang][key], `${lang}.${key}`).toBeTruthy();
      const step = MESSAGES[lang].step as Record<string, string>;
      for (const tool of ['desktop_menu', 'desktop_batch', 'desktop_open', 'desktop_takeover']) expect(step[tool]).toBeTruthy();
    }
  });
});

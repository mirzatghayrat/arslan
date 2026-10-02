import { describe, expect, it } from 'vitest';
import type { Activity, Feed, FeedEvent } from '../island/feed';
import {
  applyFeed, countdown, dismiss, hitRect, hoverEnter, hoverLeave, initialState, mood, open, setMainFocused,
  setPresence, shape, tick, COMPACT_TO_EXPAND_MS, FINISHED_MS, IDLE_COLLAPSE_MS, LEAVE_COLLAPSE_MS,
  PEEK_TO_EXPAND_MS, STEP_HISTORY, type IslandState,
} from '../island/islandMachine';

const act = (over: Partial<Activity> = {}): Activity => ({
  id: 1, conversation_id: 'c1', kind: 'job', title: 'Find 10 jobs', started_at: 100,
  step: { tool: 'write_file', target: 'jobs.csv', at: 101 }, plan: null, ...over,
});
const ev = (over: Partial<FeedEvent> = {}): FeedEvent => ({
  id: 1, kind: 'turn_finished', conversation_id: 'c1', outcome: 'ok', task_id: null, at: 1,
  title: 'Find 10 jobs', summary: 'Saved jobs.csv', work: 'job', ...over,
});
const feed = (over: Partial<Feed> = {}): Feed => ({
  cursor: 0, awaiting: 0, awaiting_conversations: [], active: [], events: [], enabled: true, ...over,
});
/** A state that has had its first poll (cursor adopted). */
const started = (now = 0, over: Partial<Feed> = {}) => applyFeed(initialState(), feed({ cursor: 10, ...over }), now);
const finishedFeed = (id: number, over: Partial<FeedEvent> = {}) => feed({ cursor: id, events: [ev({ id, ...over })] });

describe('island behaviour', () => {
  it('the first poll adopts the cursor and replays nothing', () => {
    const s = applyFeed(initialState(), feed({ cursor: 5, events: [ev({ id: 5 })] }), 0);
    expect(s.cursor).toBe(5);
    expect(s.current).toBeNull();
    expect(s.mode).toBe('hidden');
  });

  it('shows a strip while work runs, hides while you are away, comes back', () => {
    let s = applyFeed(started(), feed({ cursor: 10, active: [act()] }), 1);
    expect(s.mode).toBe('compact');
    s = setPresence(s, true, 2);
    expect(s.mode).toBe('hidden');
    expect(mood(s)).toBe('sleeping');
    s = setPresence(s, false, 3);
    expect(s.mode).toBe('compact');
  });

  it('hover on the notch peeks, then opens after 650 ms; leaving closes after a short grace', () => {
    let s = hoverEnter(started(), 1000);
    expect(s.mode).toBe('peek');
    s = tick(s, 1000 + PEEK_TO_EXPAND_MS - 1);
    expect(s.mode).toBe('peek');
    s = tick(s, 1000 + PEEK_TO_EXPAND_MS);
    expect([s.mode, s.view]).toEqual(['expanded', 'empty']);
    s = hoverLeave(s, 5000);
    expect(tick(s, 5000 + LEAVE_COLLAPSE_MS - 1).mode).toBe('expanded');
    expect(tick(s, 5000 + LEAVE_COLLAPSE_MS).mode).toBe('hidden');
  });

  it('hover on the strip opens the overview after 200 ms and rests back to the strip', () => {
    let s = applyFeed(started(), feed({ cursor: 10, active: [act()] }), 0);
    s = hoverEnter(s, 1000);
    expect(tick(s, 1000 + COMPACT_TO_EXPAND_MS - 1).mode).toBe('compact');
    s = tick(s, 1000 + COMPACT_TO_EXPAND_MS);
    expect([s.mode, s.view]).toEqual(['expanded', 'overview']);
    s = tick(hoverLeave(s, 2000), 2000 + LEAVE_COLLAPSE_MS);
    expect(s.mode).toBe('compact');
  });

  it('a waiting card opens the island by itself and keeps it open', () => {
    let s = applyFeed(started(), feed({ cursor: 10, awaiting: 1, awaiting_conversations: ['c1'], active: [act()] }), 0);
    expect([s.mode, s.view]).toEqual(['expanded', 'needsYou']);
    expect(mood(s)).toBe('approval');
    s = tick(s, 10 * IDLE_COLLAPSE_MS);
    expect(s.view).toBe('needsYou');
    // Away does not hide something that needs you.
    expect(setPresence(s, true, 1).view).toBe('needsYou');
  });

  it('closing a waiting card keeps it closed until another card arrives', () => {
    let s = applyFeed(started(), feed({ cursor: 10, awaiting: 1, active: [act()] }), 0);
    s = dismiss(s, 1);
    expect(s.mode).toBe('compact');
    expect(mood(s)).toBe('approval');                  // the strip still says something waits
    s = applyFeed(s, feed({ cursor: 10, awaiting: 1, active: [act()] }), 2);
    expect(s.mode).toBe('compact');
    s = applyFeed(s, feed({ cursor: 10, awaiting: 2, active: [act()] }), 3);
    expect(s.view).toBe('needsYou');
    s = applyFeed(s, feed({ cursor: 10, awaiting: 0, active: [act()] }), 4);
    expect(s.mode).toBe('compact');
    expect(s.needsYouSeen).toBe(0);
  });

  it('a finished job shows for 5.2 s, longer while you read it', () => {
    let s = applyFeed(started(), finishedFeed(11), 1000);
    expect([s.mode, s.view, s.current?.summary]).toEqual(['expanded', 'finished', 'Saved jobs.csv']);
    expect(mood(s)).toBe('finished');
    expect(tick(s, 1000 + FINISHED_MS - 1).view).toBe('finished');
    expect(tick(s, 1000 + FINISHED_MS).mode).toBe('hidden');
    const showing = (x: IslandState) => [x.mode, x.view, x.current?.title];
    s = hoverEnter(s, 2000);
    expect(showing(tick(s, 60_000))).toEqual(['expanded', 'finished', 'Find 10 jobs']);   // never closes under the pointer
    s = hoverLeave(s, 60_000);
    expect(showing(tick(s, 61_999))).toEqual(['expanded', 'finished', 'Find 10 jobs']);   // at least 2 s after you move away
    expect(showing(tick(s, 62_000))).toEqual(['hidden', 'finished', undefined]);
  });

  it('a chat turn you are looking at does not pop up; a background job still does', () => {
    const s = setMainFocused(started(), true);
    expect(applyFeed(s, finishedFeed(11, { work: 'turn' }), 1).current).toBeNull();
    expect(applyFeed(s, finishedFeed(11, { work: null }), 1).current).toBeNull();   // unknown → a turn
    expect(applyFeed(s, finishedFeed(11, { work: 'job' }), 1).current?.kind).toBe('finished');
    expect(applyFeed(setMainFocused(s, false), finishedFeed(11, { work: 'turn' }), 1).current?.kind).toBe('finished');
  });

  it('maps outcomes: cancelled is silent, errors and reviews stop, a failed-then-paused task is one notice', () => {
    const s = started();
    expect(applyFeed(s, finishedFeed(11, { outcome: 'cancelled' }), 1).mode).toBe('hidden');
    expect(applyFeed(s, finishedFeed(11, { outcome: 'error' }), 1).current?.reason).toBe('error');
    expect(applyFeed(s, finishedFeed(11, { outcome: 'needs_review' }), 1).current?.reason).toBe('needs_review');
    const failed = feed({ cursor: 13, events: [
      ev({ id: 12, kind: 'scheduled_finished', outcome: 'error', task_id: 7, work: 'scheduled', title: 'Daily brief' }),
      ev({ id: 13, kind: 'scheduled_paused', outcome: null, task_id: 7, work: null, title: 'Daily brief' }),
    ] });
    const shown = applyFeed(s, failed, 1);
    expect([shown.current?.reason, shown.queue.length]).toEqual(['paused', 0]);
    expect(mood(shown)).toBe('stopped');
  });

  it('a stopped notice closes after 60 s without interaction, with a countdown in the last 10 s', () => {
    const s = applyFeed(started(), finishedFeed(11, { outcome: 'error' }), 0);
    expect(countdown(s, 49_000)).toBe(0);
    expect(countdown(s, 55_000)).toBeCloseTo(0.5);
    expect(tick(s, IDLE_COLLAPSE_MS - 1).view).toBe('stopped');
    expect(tick(s, IDLE_COLLAPSE_MS).mode).toBe('hidden');
  });

  it('results queue and show one after another', () => {
    let s = applyFeed(started(), feed({ cursor: 12, events: [ev({ id: 11, title: 'A' }), ev({ id: 12, title: 'B' })] }), 0);
    expect([s.current?.title, s.queue.length]).toEqual(['A', 1]);
    s = tick(s, FINISHED_MS);
    expect(s.current?.title).toBe('B');
    s = tick(s, 2 * FINISHED_MS);
    expect(s.current).toBeNull();
  });

  it('a result waits while you read other running work, then shows', () => {
    const other = act({ id: 2, conversation_id: 'c2', title: 'Sort downloads' });
    let s = applyFeed(started(), feed({ cursor: 10, active: [act(), other] }), 0);
    s = tick(hoverEnter(s, 0), COMPACT_TO_EXPAND_MS);
    s = applyFeed(s, feed({ cursor: 11, active: [other], events: [ev({ id: 11 })] }), 300);
    expect([s.view, s.queue.length]).toEqual(['overview', 1]);
    s = tick(hoverLeave(s, 400), 400 + LEAVE_COLLAPSE_MS);
    expect(s.view).toBe('finished');
  });

  it('when the work you are watching was the last one, its result shows at once', () => {
    let s = applyFeed(started(), feed({ cursor: 10, active: [act()] }), 0);
    s = tick(hoverEnter(s, 0), COMPACT_TO_EXPAND_MS);
    s = applyFeed(s, finishedFeed(11), 300);
    expect([s.view, s.current?.title]).toEqual(['finished', 'Find 10 jobs']);
  });

  it('a click opens whatever matters most', () => {
    expect(open(started(), 0).view).toBe('empty');
    expect(open(applyFeed(started(), feed({ cursor: 10, active: [act()] }), 0), 0).view).toBe('overview');
  });

  it('turned off in Settings: nothing shows and nothing takes the pointer', () => {
    const s = applyFeed(started(), feed({ cursor: 10, enabled: false, active: [act()], awaiting: 1 }), 0);
    expect(s.mode).toBe('hidden');
    expect(hitRect(s, { notch: true, notchWidth: 200, barHeight: 32 }, 720)).toEqual({ x: 0, y: 0, w: 0, h: 0 });
  });

  it('the mascot searches while reading the web and works otherwise', () => {
    const at = (tool: string) => mood(applyFeed(started(), feed({ cursor: 10, active: [act({ step: { tool, target: null, at: 1 } })] }), 0));
    expect(at('web_search')).toBe('searching');
    expect(at('browser_open')).toBe('searching');
    expect(at('write_file')).toBe('working');
    expect(mood(started())).toBe('idle');
  });

  it('keeps a short history of distinct steps per run', () => {
    let s = started();
    for (let i = 0; i < 6; i++) {
      s = applyFeed(s, feed({ cursor: 10, active: [act({ step: { tool: 'web_extract', target: `h${i}`, at: i } })] }), i);
      s = applyFeed(s, feed({ cursor: 10, active: [act({ step: { tool: 'web_extract', target: `h${i}`, at: i } })] }), i);
    }
    expect(s.steps[1].map((x) => x.target)).toEqual(['h2', 'h3', 'h4', 'h5'].slice(-STEP_HISTORY));
    s = applyFeed(s, feed({ cursor: 10 }), 9);
    expect(s.steps).toEqual({});
  });
});

describe('island geometry', () => {
  const notch = { notch: true, notchWidth: 186, barHeight: 33 };
  const flat = { notch: false, notchWidth: 200, barHeight: 24 };
  const at = (mode: IslandState['mode'], view: IslandState['view'] = 'empty') => ({ ...initialState(), mode, view });

  it('hides exactly behind the notch and grows out of it', () => {
    expect(shape(at('hidden'), notch)).toEqual({ w: 186, h: 33, r: 12 });
    expect(shape(at('compact'), notch).w).toBe(186 + 120);
    expect(shape(at('expanded', 'overview'), notch)).toEqual({ w: 640, h: 210, r: 30 });
  });

  it('takes the pointer over the shape plus its ears, centred in the window', () => {
    expect(hitRect(at('hidden'), notch, 720)).toEqual({ x: 253, y: 0, w: 214, h: 33 });
    expect(hitRect(at('hidden'), flat, 720)).toEqual({ x: 320, y: 0, w: 80, h: 22 });
  });
});

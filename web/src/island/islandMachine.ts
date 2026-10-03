/**
 * The island's behaviour as pure transitions (0.1.51 I1). Time is passed in, so
 * every rule is testable without timers; IslandApp feeds it events and a tick.
 *
 * Modes: hidden (behind the notch) · peek (pointer on it) · compact (a strip
 * while work runs) · expanded (a panel). Where the island rests when nobody is
 * pointing at it, in order: something needs you → expanded and stays; a
 * finished/stopped result → expanded for a while; you are away → hidden; work
 * running → compact; otherwise hidden.
 */
import type { Activity, Feed, FeedEvent, WorkKind } from './feed';

export type Mode = 'hidden' | 'peek' | 'compact' | 'expanded';
export type View = 'overview' | 'empty' | 'needsYou' | 'finished' | 'stopped';
export type Mood = 'idle' | 'working' | 'searching' | 'approval' | 'finished' | 'stopped' | 'sleeping';

export interface Alert {
  id: number;
  kind: 'finished' | 'stopped';
  reason: 'done' | 'needs_review' | 'error' | 'paused';
  title: string | null;
  summary: string | null;
  conversationId: string | null;
  taskId: number | null;
  work: WorkKind;
}

export interface StepLine { tool: string; target: string | null; at: number }

export interface IslandState {
  enabled: boolean;
  mode: Mode;
  view: View;
  cursor: number | null;
  active: Activity[];
  steps: Record<number, StepLine[]>;
  awaiting: number;
  awaitingConversations: string[];
  needsYouSeen: number;
  queue: Alert[];
  current: Alert | null;
  shownAt: number;
  away: boolean;
  mainFocused: boolean;
  hovering: boolean;
  hoverSince: number;
  leftAt: number;
  lastInteract: number;
  focusId: number | null;
  /** 0.1.52 S5: practices learned since you last closed or opened from the island ("+1 practice"). */
  learned: number;
}

export const PEEK_TO_EXPAND_MS = 650;
export const COMPACT_TO_EXPAND_MS = 200;
export const PEEK_LEAVE_MS = 600;
export const LEAVE_COLLAPSE_MS = 1200;
export const FINISHED_MS = 5200;
export const IDLE_COLLAPSE_MS = 60_000;
export const COUNTDOWN_MS = 10_000;
export const MAX_QUEUE = 5;
export const STEP_HISTORY = 4;

const SEARCH_TOOLS = new Set(['web_search', 'web_extract', 'recall']);
export const isSearchTool = (tool: string | undefined) =>
  !!tool && (SEARCH_TOOLS.has(tool) || tool.startsWith('browser_'));

export function initialState(): IslandState {
  return {
    enabled: true, mode: 'hidden', view: 'empty', cursor: null, active: [], steps: {},
    awaiting: 0, awaitingConversations: [], needsYouSeen: 0, queue: [], current: null, shownAt: 0,
    away: false, mainFocused: false, hovering: false, hoverSince: 0, leftAt: -Infinity,
    lastInteract: 0, focusId: null, learned: 0,
  };
}

const needsYou = (s: IslandState) => s.awaiting > 0 && s.awaiting > s.needsYouSeen;

/** One feed event → what the island should show for it, or null for nothing. */
export function alertFor(e: FeedEvent, previous: Activity[], mainFocused: boolean): Alert | null {
  const base = { id: e.id, title: e.title, summary: e.summary, conversationId: e.conversation_id, taskId: e.task_id };
  if (e.kind === 'scheduled_paused') return { ...base, kind: 'stopped', reason: 'paused', work: 'scheduled' };
  if (e.kind !== 'turn_finished' && e.kind !== 'scheduled_finished') return null;
  const work: WorkKind = e.work
    ?? (e.kind === 'scheduled_finished' ? 'scheduled'
      : previous.find((a) => a.conversation_id && a.conversation_id === e.conversation_id)?.kind ?? 'turn');
  if (e.outcome === 'cancelled' || e.outcome === null) return null;   // you stopped it yourself
  if (work === 'turn' && mainFocused) return null;                      // you are looking at the answer
  if (e.outcome === 'ok') return { ...base, kind: 'finished', reason: 'done', work };
  return { ...base, kind: 'stopped', reason: e.outcome === 'error' ? 'error' : 'needs_review', work };
}

function trackSteps(prev: Record<number, StepLine[]>, active: Activity[]): Record<number, StepLine[]> {
  const out: Record<number, StepLine[]> = {};
  for (const a of active) {
    const hist = prev[a.id] ?? [];
    const last = hist[hist.length - 1];
    const s = a.step;
    out[a.id] = s && (!last || last.at !== s.at || last.tool !== s.tool || last.target !== s.target)
      ? [...hist, { tool: s.tool, target: s.target, at: s.at }].slice(-STEP_HISTORY)
      : hist;
  }
  return out;
}

function enqueue(queue: Alert[], alert: Alert): Alert[] {
  // A scheduled task that failed and was then paused is one thing, not two.
  const rest = alert.reason === 'paused' && alert.taskId !== null
    ? queue.filter((q) => !(q.taskId === alert.taskId && q.kind === 'stopped'))
    : queue;
  return [...rest, alert].slice(-MAX_QUEUE);
}

export function applyFeed(s: IslandState, feed: Feed, now: number): IslandState {
  if (!feed.enabled) {
    return { ...initialState(), enabled: false, cursor: feed.cursor, away: s.away, mainFocused: s.mainFocused };
  }
  let queue = s.queue;
  let current = s.current;
  let learned = s.learned;
  if (s.cursor !== null) {   // the first poll adopts the cursor: no replay of history
    for (const e of feed.events) {
      if (e.id <= s.cursor) continue;
      if (e.kind === 'lesson_learned') { learned += 1; continue; }   // quiet: counted, never a card
      const alert = alertFor(e, s.active, s.mainFocused);
      if (!alert) continue;
      if (alert.reason === 'paused' && current && current.taskId === alert.taskId && current.kind === 'stopped') {
        current = { ...current, reason: 'paused' };
        continue;
      }
      queue = enqueue(queue, alert);
    }
  }
  const active = feed.active;
  const focusId = active.some((a) => a.id === s.focusId) ? s.focusId : (active.length ? active[active.length - 1].id : null);
  const next: IslandState = {
    ...s, enabled: true, cursor: feed.cursor, active, steps: trackSteps(s.steps, active), queue, current, focusId, learned,
    awaiting: feed.awaiting, awaitingConversations: feed.awaiting_conversations,
    needsYouSeen: feed.awaiting === 0 ? 0 : Math.min(s.needsYouSeen, feed.awaiting),
  };
  return settle(next, now);
}

/** True while the pointer (or the short grace after it left) keeps a user-opened state. */
function held(s: IslandState, now: number): boolean {
  if (s.mode === 'peek') return s.hovering || now - s.leftAt < PEEK_LEAVE_MS;
  if (s.mode === 'expanded' && (s.view === 'overview' || s.view === 'empty')) {
    return s.hovering || now - s.leftAt < LEAVE_COLLAPSE_MS;
  }
  return false;
}

function show(s: IslandState, mode: Mode, view: View | null, now: number): IslandState {
  const v = view ?? s.view;
  if (s.mode === mode && s.view === v) return s;
  return { ...s, mode, view: v, lastInteract: mode === 'expanded' && s.mode !== 'expanded' ? now : s.lastInteract };
}

/** Where the island goes now, given what is pending; keeps what the pointer holds open. */
export function settle(s: IslandState, now: number): IslandState {
  if (!s.enabled) return show(s, 'hidden', null, now);
  if (needsYou(s)) return show(s, 'expanded', 'needsYou', now);
  let next = s;
  // A result does not jump in under the pointer while you are reading other
  // work that is still running; when nothing is left running it shows at once.
  const waitForPointer = held(next, now) && next.active.length > 0;
  if (!next.current && next.queue.length && !waitForPointer) {
    next = { ...next, current: next.queue[0], queue: next.queue.slice(1), shownAt: now, lastInteract: now };
  }
  if (next.current) return show(next, 'expanded', next.current.kind, now);
  if (held(next, now)) {
    if (next.mode === 'expanded') return show(next, 'expanded', next.active.length ? 'overview' : 'empty', now);
    return next;
  }
  if (next.away) return show(next, 'hidden', null, now);
  return show(next, next.active.length ? 'compact' : 'hidden', null, now);
}

export function hoverEnter(s: IslandState, now: number): IslandState {
  if (s.hovering) return s;
  const next = { ...s, hovering: true, hoverSince: now, lastInteract: now };
  return s.mode === 'hidden' && s.enabled ? { ...next, mode: 'peek' } : next;
}

export function hoverLeave(s: IslandState, now: number): IslandState {
  if (!s.hovering) return s;
  const next = { ...s, hovering: false, leftAt: now };
  // Reading a result and moving away leaves it on screen a little longer.
  if (s.current?.kind === 'finished') next.shownAt = Math.max(s.shownAt, now - FINISHED_MS + 2000);
  return next;
}

export function interact(s: IslandState, now: number): IslandState {
  return now - s.lastInteract < 250 ? s : { ...s, lastInteract: now };
}

/** A click on the strip or the mascot opens the panel for whatever is most relevant. */
export function open(s: IslandState, now: number): IslandState {
  if (!s.enabled) return s;
  const view: View = needsYou(s) ? 'needsYou' : s.current ? s.current.kind : (s.active.length ? 'overview' : 'empty');
  return { ...show(s, 'expanded', view, now), lastInteract: now, learned: 0 };
}

/** Close: the result goes away, a waiting card stays waiting (in the chat) but stops holding the panel. */
export function dismiss(s: IslandState, now: number): IslandState {
  let next: IslandState = { ...s, hovering: false, leftAt: -Infinity, learned: 0 };
  if (s.view === 'needsYou') next.needsYouSeen = s.awaiting;
  else if (s.current) next.current = null;
  next = settle({ ...next, mode: next.mode === 'peek' ? 'hidden' : next.mode }, now);
  // Closed by hand: rest instead of being held open by the grace period.
  if (next.mode === 'expanded' && (next.view === 'overview' || next.view === 'empty')) {
    next = show(next, next.away ? 'hidden' : (next.active.length ? 'compact' : 'hidden'), null, now);
  }
  return next;
}

export function setPresence(s: IslandState, away: boolean, now: number): IslandState {
  return s.away === away ? s : settle({ ...s, away }, now);
}

export function setMainFocused(s: IslandState, focused: boolean): IslandState {
  return s.mainFocused === focused ? s : { ...s, mainFocused: focused };
}

export function setFocus(s: IslandState, id: number, now: number): IslandState {
  return s.active.some((a) => a.id === id) ? { ...s, focusId: id, lastInteract: now } : s;
}

export function tick(s: IslandState, now: number): IslandState {
  if (s.mode === 'peek' && s.hovering && now - s.hoverSince >= PEEK_TO_EXPAND_MS) {
    return show(s, 'expanded', s.active.length ? 'overview' : 'empty', now);
  }
  if (s.mode === 'compact' && s.hovering && now - s.hoverSince >= COMPACT_TO_EXPAND_MS) {
    return show(s, 'expanded', s.active.length ? 'overview' : 'empty', now);
  }
  if (s.hovering) return s;
  if (s.view === 'finished' && s.mode === 'expanded' && now - s.shownAt >= FINISHED_MS) {
    return settle({ ...s, current: null }, now);
  }
  if (s.view === 'stopped' && s.mode === 'expanded' && now - s.lastInteract >= IDLE_COLLAPSE_MS) {
    return settle({ ...s, current: null }, now);
  }
  if ((s.mode === 'peek' || (s.mode === 'expanded' && (s.view === 'overview' || s.view === 'empty'))) && !held(s, now)) {
    return settle(s, now);
  }
  return s;
}

/** 0…1 for the thin bar that shows the panel is about to close; 0 hides it. */
export function countdown(s: IslandState, now: number): number {
  if (s.mode !== 'expanded' || s.hovering) return 0;
  if (s.view === 'finished') return Math.max(0, 1 - (now - s.shownAt) / FINISHED_MS);
  if (s.view === 'stopped') {
    const left = IDLE_COLLAPSE_MS - (now - s.lastInteract);
    return left < COUNTDOWN_MS ? Math.max(0, left / COUNTDOWN_MS) : 0;
  }
  return 0;
}

export function focused(s: IslandState): Activity | null {
  return s.active.find((a) => a.id === s.focusId) ?? null;
}

/** The activity a waiting card belongs to, when the feed can tell. */
export function waitingActivity(s: IslandState): Activity | null {
  const cid = s.awaitingConversations[0];
  return (cid && s.active.find((a) => a.conversation_id === cid)) || null;
}

export function mood(s: IslandState): Mood {
  if (needsYou(s) || (s.awaiting > 0 && s.mode === 'compact')) return 'approval';
  if (s.mode === 'expanded' && s.view === 'finished') return 'finished';
  if (s.mode === 'expanded' && s.view === 'stopped') return 'stopped';
  if (s.away) return 'sleeping';
  const a = focused(s);
  if (!a) return 'idle';
  return isSearchTool(a.step?.tool) ? 'searching' : 'working';
}

export interface ScreenGeometry { notch: boolean; notchWidth: number; barHeight: number }
export interface Shape { w: number; h: number; r: number }

export const VIEW_H: Record<View, number> = { overview: 210, empty: 150, needsYou: 190, finished: 176, stopped: 186 };
export const EXPANDED_W = 640;
export const EAR = 14;
/** Where the panel's cards start; VIEW_H assumes this. */
export const BODY_TOP = 36;
const BELOW_NOTCH = 6;

/**
 * The cards start below the notch: on a display whose notch is taller than
 * the default header (e.g. 39 pt at "More Space"), the notch hid the top of
 * the card (seen on a real MacBook, 0.1.51). The panel grows by the same amount.
 */
export function bodyTop(g: ScreenGeometry): number {
  return g.notch ? Math.max(BODY_TOP, Math.ceil(g.barHeight) + BELOW_NOTCH) : BODY_TOP;
}

export function shape(s: IslandState, g: ScreenGeometry): Shape {
  if (s.mode === 'expanded') return { w: EXPANDED_W, h: VIEW_H[s.view] + bodyTop(g) - BODY_TOP, r: 30 };
  if (!g.notch) {
    if (s.mode === 'compact') return { w: 240, h: 26, r: 13 };
    if (s.mode === 'peek') return { w: 140, h: 26, r: 13 };
    return { w: 80, h: 22, r: 11 };
  }
  const h = Math.max(24, g.barHeight);
  if (s.mode === 'compact') return { w: g.notchWidth + 120, h, r: 14 };
  if (s.mode === 'peek') return { w: g.notchWidth + 64, h, r: 14 };
  return { w: g.notchWidth, h, r: 12 };
}

/** The rectangle (window points) that takes the pointer; everything else clicks through. */
export function hitRect(s: IslandState, g: ScreenGeometry, windowWidth: number) {
  if (!s.enabled) return { x: 0, y: 0, w: 0, h: 0 };
  const { w, h } = shape(s, g);
  const ear = g.notch ? EAR : 0;
  return { x: Math.round((windowWidth - w) / 2 - ear), y: 0, w: Math.round(w + 2 * ear), h: Math.round(h) };
}

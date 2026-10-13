/** 0.1.61 §A4 (PR 2b final review, M3): an AppleScript card is asked as the app it names (`kind: "app"`, the bundle id), so the yes the island
 *  takes — "Allow for this task" — also lets Arslan Hands look at and act in that app for the task (spec §A5: one list of allowed apps, shared by
 *  Hands and osascript). The chat card says so in `grant.mac_script`; the island says it in one short line of its own, in six languages, and only
 *  on that card. */
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IslandApp from '../island/IslandApp';
import { alsoAllowsKey } from '../island/islandAsk';
import { LANGS, MESSAGES, t as islandText } from '../locales/island';
import type { PendingCard } from '../island/feed';

const card = (frame: PendingCard['frame'], over: Partial<PendingCard> = {}): PendingCard =>
  ({ call_id: 'k1', conversation_id: 'c1', opened_at: 1000, expires_at: 1300, island_ok: true, frame, ...over });
const SCRIPT = { type: 'propose_action', kind: 'mac_script', target: 'AppleScript · Notes', detail: 'tell application "Notes" to get name of every note',
  perm_kind: 'app', options: ['task', 'conversation', 'always'] };

describe('which cards get the line', () => {
  it('an AppleScript card asked as an app does', () => {
    expect(alsoAllowsKey(card(SCRIPT))).toBe('scriptAlsoHands');
  });

  it.each([
    ['a Hands app card', { ...SCRIPT, kind: 'desktop_app' }],
    ['a site card', { type: 'propose_action', kind: 'browser_site', target: 'example.com', perm_kind: 'site', options: ['task'] }],
    ['a Shortcut card', { type: 'propose_action', kind: 'mac_shortcut', target: 'Morning', perm_kind: 'shortcut', options: ['task'] }],
    ['a script that deletes (an app_risky card)', { ...SCRIPT, perm_kind: 'app_risky', options: ['once'] }],
    ['a script with no permission kind (a card from before 0.1.61)', { type: 'propose_action', kind: 'mac_script', target: 'Notes', detail: 'tell application "Notes" to get name' }],
    ['a script card whose kind is not a string', { ...SCRIPT, perm_kind: ['app'] }],
    ['a command', { type: 'propose_run_command', pretty: 'ls', perm_kind: 'command' }],
  ])('%s does not', (_what, frame) => {
    expect(alsoAllowsKey(card(frame as PendingCard['frame']))).toBeNull();
  });
});

describe('what the island prints', () => {
  const feed = { cursor: 3, awaiting: 1, awaiting_conversations: ['c1'], events: [], enabled: true, active: [] };
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); localStorage.clear(); });
  async function mount(held: PendingCard, lang: string) {
    localStorage.setItem('i18nextLng', lang);
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.startsWith('/api/v1/island/feed')) return new Response(JSON.stringify(feed), { status: 200 });
      if (url === '/api/v1/approvals/pending') return new Response(JSON.stringify([held]), { status: 200 });
      return new Response('{}', { status: 200 });
    }));
    render(<IslandApp />);
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
  }

  it.each(LANGS)('%s: an AppleScript card says the yes also lets Arslan look at and act in the app for this task, next to Allow', async (lang) => {
    await mount(card(SCRIPT), lang);
    expect(screen.getByTestId('island-also').textContent).toBe(islandText(lang, 'scriptAlsoHands'));
    expect(screen.getByTestId('island-allow')).toHaveTextContent(islandText(lang, 'allowTask'));      // it can be allowed here, for this task
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('AppleScript · Notes');
  });

  it.each(LANGS)('%s: the line is about looking AND acting, in this app, for this task', (lang) => {
    const topic: Record<(typeof LANGS)[number], RegExp[]> = {
      en: [/look at/, /act in/, /this app/, /this task/], zh: [/查看/, /操作/, /这个 App/, /本次任务/], ja: [/見て/, /操作/, /このアプリ/, /このタスク/],
      es: [/mire/, /actúe/, /esta app/, /esta tarea/], de: [/anzusehen/, /handeln/, /diese App/, /diese Aufgabe/], fr: [/regarder/, /agir/, /cette app/, /cette tâche/],
    };
    const line = MESSAGES[lang].scriptAlsoHands as string;
    for (const part of topic[lang]) expect(line, `${lang}: ${part}`).toMatch(part);
  });

  it.each(['desktop_app', 'browser_site'])('a %s card has no such line', async (kind) => {
    await mount(card({ ...SCRIPT, kind, perm_kind: kind === 'desktop_app' ? 'app' : 'site' }), 'en');
    expect(screen.queryByTestId('island-also')).toBeNull();
    expect(screen.getByTestId('island-allow')).toBeInTheDocument();
  });
});

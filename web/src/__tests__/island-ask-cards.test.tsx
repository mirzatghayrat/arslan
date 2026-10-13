/** 0.1.61 §A4 (PR 2b Task 4): the island answers a card from the permission layer only with its first choice (it still sends just
 *  `approve`; the server holds the scope to options[0]), and reads it as the Inbox and the chat do: a kind it has no words for is asked
 *  in the model's why with the server's literal subject line under it, a kind it has words for keeps them and shows the why as
 *  "Arslan says", a title of spaces is no title, a long unbroken line wraps instead of being cut off. And one gesture answers one card
 *  here too: for 500 ms after the card shown changes, neither button answers, and both look it (aria-disabled). */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IslandApp from '../island/IslandApp';
import { LANGS, MESSAGES } from '../locales/island';
import en from '../locales/en.json';
import zh from '../locales/zh.json';
import ja from '../locales/ja.json';
import es from '../locales/es.json';
import de from '../locales/de.json';
import fr from '../locales/fr.json';
import { allowKey, askLine, askWhy, knowsKind } from '../island/islandAsk';
import type { PendingCard } from '../island/feed';

const feed = (over: Record<string, unknown> = {}) => ({ cursor: 3, awaiting: 0, awaiting_conversations: [], events: [], enabled: true, active: [], ...over });
const card = (over: Partial<PendingCard> & { frame: PendingCard['frame'] }): PendingCard => ({
  call_id: 'k1', conversation_id: 'c1', opened_at: 1000, expires_at: 1300, island_ok: true, ...over,
});
const NAMES: Record<string, string> = { a: 'Alpha', b: 'Bravo' };
const schedule = (id: string, name = NAMES[id] ?? id) => card({ call_id: id, frame: { type: 'propose_schedule', name, when: 'every: 3600', options: ['once', 'conversation'] } });

/** a server whose pending list moves: an answer takes its card out of it */
let live: { pending: PendingCard[] };
let calls: { url: string; init?: RequestInit }[] = [];
function serve(pending: PendingCard[]) {
  live = { pending };
  calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.startsWith('/api/v1/island/feed')) {
      return new Response(JSON.stringify(feed({ awaiting: live.pending.length, awaiting_conversations: live.pending.map((c) => c.conversation_id) })), { status: 200 });
    }
    if (url === '/api/v1/approvals/pending') return new Response(JSON.stringify(live.pending), { status: 200 });
    const m = /^\/api\/v1\/approvals\/([^/]+)\/answer$/.exec(url);
    if (m) { live.pending = live.pending.filter((c) => c.call_id !== m[1]); return new Response('{}', { status: 200 }); }
    return new Response('{"ok":true}', { status: 200 });
  }));
}
const answers = () => calls.filter((c) => c.url.includes('/answer') && c.init?.method === 'POST').map((c) => c.url.split('/')[4]);
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const click = (id: string) => act(async () => { fireEvent.click(screen.getByTestId(id)); await vi.advanceTimersByTimeAsync(10); });

beforeEach(() => { vi.useFakeTimers(); localStorage.setItem('i18nextLng', 'en'); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });
async function mount() { render(<IslandApp />); await advance(20); }

describe('what the island says for an action card from the permission layer', () => {
  const ACTION = { type: 'propose_action', kind: 'mcp_tool', target: 'rea/search', title: 'Use rea’s search?', options: ['task', 'conversation'] };

  it('a kind it has no words for is asked in the model’s why; the server’s literal title sits under it', async () => {
    serve([card({ frame: { ...ACTION, why: 'Look up the opening hours' } })]);
    await mount();
    expect(screen.getByTestId('island-ask-why')).toHaveTextContent('Look up the opening hours');
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('Use rea’s search?');
    expect(screen.queryByTestId('island-ask-said')).toBeNull();
  });

  it('with no title the line under the why is the bare target', async () => {
    serve([card({ frame: { ...ACTION, title: undefined, why: 'Look up the opening hours' } })]);
    await mount();
    expect(screen.getByTestId('island-ask-line').textContent).toBe('rea/search');
  });

  it('with no why the title is the question, said once', async () => {
    serve([card({ frame: ACTION })]);
    await mount();
    expect(screen.queryByTestId('island-ask-why')).toBeNull();
    expect(screen.queryByTestId('island-ask-said')).toBeNull();
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('Use rea’s search?');
  });

  it('a kind it has words for keeps its line (the target) and shows the why as “Arslan says”', async () => {
    serve([card({ frame: { ...ACTION, kind: 'desktop_app', target: 'Notes', title: 'Use Notes?', why: 'Tidy the notes' } })]);
    await mount();
    expect(screen.getByTestId('island-ask-line').textContent).toBe('Notes');
    expect(screen.getByTestId('island-ask-said')).toHaveTextContent('Arslan says: Tidy the notes');
    expect(screen.queryByTestId('island-ask-why')).toBeNull();
  });

  it('a why of spaces says nothing, in either case', async () => {
    serve([card({ frame: { ...ACTION, why: '   ' } })]);
    await mount();
    expect(screen.queryByTestId('island-ask-why')).toBeNull();
    expect(screen.queryByTestId('island-ask-said')).toBeNull();
    cleanup();
    serve([card({ frame: { ...ACTION, kind: 'desktop_app', target: 'Notes', why: ' \n ' } })]);
    await mount();
    expect(screen.queryByTestId('island-ask-said')).toBeNull();
  });

  it('a title of spaces is no title: the line is the target, never a blank one', () => {
    expect(askLine(card({ frame: { ...ACTION, title: '   ' } }))).toBe('rea/search');
    expect(askLine(card({ frame: { ...ACTION, title: ' \n ', why: 'Look up' } }))).toBe('rea/search');
  });

  it('only an action card has a why here; the island knows which kinds it has words for', () => {
    expect(askWhy(card({ frame: { ...ACTION, why: '  Look up  ' } }))).toBe('Look up');
    expect(askWhy(card({ frame: { type: 'propose_run_command', pretty: 'ls', why: 'because' } }))).toBe('');
    expect(askWhy(card({ frame: { type: 'propose_action', kind: 'app', why: 7 } }))).toBe('');
    expect(knowsKind(card({ frame: { ...ACTION, kind: 'desktop_app' } }))).toBe(true);
    expect(knowsKind(card({ frame: ACTION }))).toBe(false);
    expect(knowsKind(card({ frame: { type: 'propose_schedule', name: 'x', when: 'every: 60' } }))).toBe(true);
    expect(knowsKind(card({ frame: { type: 'propose_action', kind: 'constructor' } }))).toBe(false);
  });

  it('one long unbroken line wraps instead of being cut off by an ellipsis', async () => {
    const url = 'https://example.com/' + 'a'.repeat(200);
    serve([card({ frame: { ...ACTION, title: url, why: url } })]);
    await mount();
    for (const id of ['island-ask-why', 'island-ask-line']) expect(screen.getByTestId(id).className).toMatch(/\bwrap\b/);
    const css = readFileSync(resolve(__dirname, '../island/island.css'), 'utf8');
    expect(document.querySelector('.cmain')?.className).toMatch(/\bask\b/);                // the ask card's own box: its buttons are never pushed out of it
    const box = /\.cmain\.ask\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
    expect(box).toMatch(/max-height:\s*100%/);
    expect(box).toMatch(/min-height:\s*0/);
    expect(/\.cmain\.ask > \*\s*\{([^}]*)\}/.exec(css)?.[1] ?? '', 'nothing gives way by default').toMatch(/flex-shrink:\s*0/);
    const gives = /\.cmain\.ask > \.ititle\.wrap, \.cmain\.ask > \.code\.wrap, \.cmain\.ask > \.itext\.said\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
    expect(gives, 'only the long lines give way').toMatch(/flex-shrink:\s*1/);
    expect(gives, 'only the long lines give way').toMatch(/min-height:\s*0/);
    const held = /\.btn\[aria-disabled="true"\]\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
    expect(held, 'a held button looks held').toMatch(/opacity:/);
    expect(held, 'a held button looks held').toMatch(/cursor:\s*not-allowed/);
    for (const selector of ['.ititle.wrap', '.code.wrap', '.itext.said']) {
      const rule = new RegExp(`${selector.replace(/\./g, '\\.')}[^{]*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';
      expect(rule, `${selector} may break anywhere`).toMatch(/overflow-wrap:\s*anywhere/);
      expect(rule, `${selector} is not one cut-off line`).not.toMatch(/white-space:\s*nowrap/);
    }
  });
});

describe('what Allow says here', () => {
  it('the first choice names it: for this task, once, or just Allow when there is no choice', () => {
    expect(allowKey(card({ frame: { type: 'propose_action', options: ['task', 'conversation', 'always'] } }))).toBe('allowTask');
    expect(allowKey(card({ frame: { type: 'propose_workspace_write', options: ['once', 'conversation'] } }))).toBe('allowOnce');
    expect(allowKey(card({ frame: { type: 'propose_workspace_write', options: ['once'] } }))).toBe('allow');
    expect(allowKey(card({ frame: { type: 'propose_run_command' } }))).toBe('allow');
    expect(allowKey(card({ frame: { type: 'propose_action', options: 'task' as never } }))).toBe('allow');
  });

  it('whatever is on the card, the island sends only approve and its source', async () => {
    serve([card({ call_id: 'w1', frame: { type: 'propose_action', kind: 'app', target: 'Notes', options: ['task', 'conversation', 'always'], always_label: 'Notes' } })]);
    await mount();
    await click('island-allow');
    expect(JSON.parse(String(calls.find((c) => c.url.includes('/approvals/w1/answer'))?.init?.body))).toEqual({ approve: true, source: 'island' });
  });
});

describe('one gesture answers one card, here too', () => {
  it('the card that moves up under the pointer is not answered by the second click of a double-click', async () => {
    serve([schedule('a'), schedule('b')]);
    await mount();
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('Alpha');
    await click('island-allow');                                     // click 1 answers a; b moves up
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('Bravo');
    await click('island-allow');                                     // click 2 of the double-click
    await click('island-decline');
    expect(answers()).toEqual(['a']);
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('Bravo');
  });

  it('the hold is shown on both buttons, and they answer again 500 ms after the card changed', async () => {
    serve([schedule('a'), schedule('b')]);
    await mount();
    expect(screen.getByTestId('island-allow')).not.toHaveAttribute('aria-disabled');      // the first card of an idle island answers at once
    expect(screen.getByTestId('island-decline')).not.toHaveAttribute('aria-disabled');
    await click('island-allow');
    for (const id of ['island-allow', 'island-decline']) {
      expect(screen.getByTestId(id)).toHaveAttribute('aria-disabled', 'true');
      expect(screen.getByTestId(id)).not.toBeDisabled();                                    // the focus stays on it
    }
    await advance(480);                                                                      // 490 ms after the card changed
    expect(screen.getByTestId('island-allow')).toHaveAttribute('aria-disabled', 'true');
    await advance(20);
    expect(screen.getByTestId('island-allow')).not.toHaveAttribute('aria-disabled');
    expect(screen.getByTestId('island-decline')).not.toHaveAttribute('aria-disabled');
    await click('island-allow');
    expect(answers()).toEqual(['a', 'b']);
  });

  it('No is held like Allow', async () => {
    serve([schedule('a'), schedule('b')]);
    await mount();
    await click('island-decline');
    await click('island-decline');
    expect(answers()).toEqual(['a']);
    await advance(500);
    await click('island-decline');
    expect(answers()).toEqual(['a', 'b']);
  });

  it('a card proposed a moment after the last one was answered is held for the rest of that time, counted from when the last one left', async () => {
    serve([schedule('a')]);
    await mount();
    // The first poll is followed by one 2.5 s later (the state that tells it to hurry is not drawn yet), then they come every second.
    await advance(2060);
    await click('island-allow');                                     // a answered ~2.08 s in
    live.pending = [schedule('b')];                                  // the next command of the turn is proposed at once
    await advance(430);                                              // the poll brings b ~2.5 s in: a left ~420 ms ago
    expect(screen.getByTestId('island-ask-line')).toHaveTextContent('Bravo');
    expect(screen.getByTestId('island-allow')).toHaveAttribute('aria-disabled', 'true');
    await click('island-allow');
    expect(answers()).toEqual(['a']);
    await advance(100);                                              // ~540 ms after a left: the 500 ms are up, though b came up only ~30 ms ago
    expect(screen.getByTestId('island-allow')).not.toHaveAttribute('aria-disabled');
    await click('island-allow');
    expect(answers()).toEqual(['a', 'b']);
  });

  it('a card that comes up after the island has been idle for a while answers at once', async () => {
    serve([schedule('a')]);
    await mount();
    await click('island-allow');
    await advance(1500);                                             // nothing waits for a good while
    live.pending = [schedule('b')];
    await advance(1100);
    expect(screen.getByTestId('island-allow')).not.toHaveAttribute('aria-disabled');
    await click('island-allow');
    expect(answers()).toEqual(['a', 'b']);
  });

  it('the hold is not the wall clock: a clock set back does not hold the card until it catches up', async () => {
    serve([schedule('a'), schedule('b')]);
    await mount();
    await click('island-allow');
    vi.setSystemTime(Date.now() - 3_600_000);                       // the system clock is set an hour back
    await advance(520);
    expect(screen.getByTestId('island-allow')).not.toHaveAttribute('aria-disabled');
    await click('island-allow');
    expect(answers()).toEqual(['a', 'b']);
  });
});

describe('the island’s own words for a card from the permission layer, in every language', () => {
  const APP: Record<string, { kit: { arslanSays: string } }> = { en, zh, ja, es, de, fr };

  it.each([...LANGS])('%s: Allow once and Allow for this task are words of their own, and “Arslan says” is the app’s', (lang) => {
    const words = MESSAGES[lang];
    for (const key of ['allowOnce', 'allowTask'] as const) {
      expect(words[key], `${lang} ${key}`).toBeTypeOf('string');
      expect(words[key].length, `${lang} ${key}`).toBeGreaterThan(words.allow.length);   // says more than Allow: the choice
    }
    expect(words.allowOnce).not.toBe(words.allowTask);
    expect(words.arslanSays).toBe(APP[lang].kit.arslanSays);                              // one word for it, here and in the app
  });

  it('English says what they grant', () => {
    expect(MESSAGES.en.allowOnce).toBe('Allow once');
    expect(MESSAGES.en.allowTask).toBe('Allow for this task');
  });
});

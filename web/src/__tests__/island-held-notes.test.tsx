/** 0.1.61 §A4 (PR 2b Task 7, fix round 1): the line under a card the island will not answer follows the card's kind. It used to be one
 *  line for all of them, "This one may delete, send or pay": wrong for a takeover (it takes over the screen), a step outside the sandbox,
 *  a system setting, a new ability, another agent's settings, code that is downloaded or decoded first, and another machine. Each of those
 *  says what it is, in six languages; "may delete, send or pay" stays for money, send, destructive and a risky step in an app; a kind the
 *  island does not know gets a neutral line, never a wrong risk. */
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IslandApp from '../island/IslandApp';
import { heldNoteKey } from '../island/islandAsk';
import { LANGS, MESSAGES, t as islandText, type MessageKey } from '../locales/island';
import type { PendingCard } from '../island/feed';

const card = (frame: PendingCard['frame']): PendingCard => ({ call_id: 'k1', conversation_id: 'c1', opened_at: 1000, expires_at: 1300, island_ok: false, frame });
const action = (perm_kind: unknown, over: Record<string, unknown> = {}) =>
  card({ type: 'propose_action', kind: 'desktop_app', target: 'Notes', detail: '', perm_kind, ...over });

const HELD: Record<string, MessageKey> = {
  takeover: 'heldTakeover', outside: 'heldOutside', system: 'heldSystem', capability: 'heldCapability',
  other_agent: 'heldOtherAgent', opaque: 'heldOpaque', remote: 'heldRemote',
};
const RISKY = ['money', 'send', 'destructive', 'app_risky'];

describe('which line a held card gets', () => {
  it.each(Object.entries(HELD))('permission kind %s -> %s', (kind, key) => {
    expect(heldNoteKey(action(kind))).toBe(key);
  });

  it.each(RISKY)('%s -> the delete / send / pay line, and only these four', (kind) => {
    expect(heldNoteKey(action(kind))).toBe('riskyNote');
  });

  it.each(['folder', 'app', 'site', 'shortcut', 'screen', 'mcp_tool', 'schedule', 'command', 'workspace_write', 'made_up', '', 'constructor', 'toString', '__proto__'])(
    'a kind %j that is none of those gets the neutral line', (kind) => {
    expect(heldNoteKey(action(kind))).toBe('heldGeneric');
  });

  it.each([[null], [['app']], [7], [{}]])('a permission kind that is not a string (%j) is read as none, never an error', (kind) => {
    expect(heldNoteKey(action(kind))).toBe('heldGeneric');
  });

  it('a card with no permission kind keeps the 0.1.55 reading: a risky step, another machine, outside the sandbox — else neutral', () => {
    expect(heldNoteKey(card({ type: 'propose_action', kind: 'desktop_risky', target: 'Mail · Send', detail: '' }))).toBe('riskyNote');
    expect(heldNoteKey(card({ type: 'propose_run_command', pretty: 'ls', remote_host: 'mini' }))).toBe('heldRemote');
    expect(heldNoteKey(card({ type: 'propose_run_command', pretty: 'mv a b', sandbox: 'outside' }))).toBe('heldOutside');
    expect(heldNoteKey(card({ type: 'propose_run_command', pretty: 'mv a b', sandbox: 'retry' }))).toBe('heldOutside');
    expect(heldNoteKey(card({ type: 'propose_run_command', pretty: 'rm a' }))).toBe('heldGeneric');
    expect(heldNoteKey(card({ type: 'propose_action', kind: 'desktop_look', target: 'Notes', detail: '' }))).toBe('heldGeneric');
  });

  it('a command card of the plain kind is read by what holds it: another machine, outside the sandbox', () => {
    expect(heldNoteKey(card({ type: 'propose_run_command', pretty: 'ls', remote_host: 'mini', perm_kind: 'command' }))).toBe('heldRemote');
    expect(heldNoteKey(card({ type: 'propose_run_command', pretty: 'mv a b', sandbox: 'outside', perm_kind: 'command' }))).toBe('heldOutside');
    expect(heldNoteKey(card({ type: 'propose_run_command', pretty: 'rm a', perm_kind: 'command' }))).toBe('heldGeneric');
  });

  it('the permission kind wins over the legacy fields on the frame', () => {
    expect(heldNoteKey(action('takeover', { kind: 'desktop_risky' }))).toBe('heldTakeover');
    expect(heldNoteKey(action('money', { remote_host: 'mini' }))).toBe('riskyNote');
  });
});

describe('the lines, in six languages', () => {
  const KEYS: MessageKey[] = [...Object.values(HELD), 'heldGeneric'];
  it.each(LANGS)('%s: every held line is written, is its own, and none says "delete, send or pay"', (lang) => {
    const lines = KEYS.map((k) => MESSAGES[lang][k] as string);
    for (const [i, line] of lines.entries()) expect(line.trim(), `${lang}.${KEYS[i]}`).not.toBe('');
    expect(new Set([...lines, MESSAGES[lang].riskyNote]).size, `${lang}: all different`).toBe(KEYS.length + 1);
  });

  // What each line is ABOUT, per language: a line moved under the wrong kind keeps its place in the table but says the wrong thing.
  const TOPIC: Record<MessageKey, Record<(typeof LANGS)[number], RegExp>> = {
    heldTakeover: { en: /screen/, zh: /屏幕/, ja: /画面/, es: /pantalla/, de: /Bildschirm/, fr: /écran/ },
    heldOutside: { en: /sandbox/, zh: /沙盒/, ja: /サンドボックス/, es: /aislado/, de: /Sandbox/, fr: /bac à sable/ },
    heldSystem: { en: /setting on your Mac/, zh: /系统设置/, ja: /Mac の設定/, es: /ajuste de tu Mac/, de: /Einstellung deines Macs/, fr: /réglage de votre Mac/ },
    heldCapability: { en: /new ability/, zh: /新能力/, ja: /新しい機能/, es: /capacidad nueva/, de: /neue Fähigkeit/, fr: /nouvelle capacité/ },
    heldOtherAgent: { en: /another agent/, zh: /另一个智能体/, ja: /ほかのエージェント/, es: /otro agente/, de: /anderen Agenten/, fr: /autre agent/ },
    heldOpaque: { en: /downloaded or decoded/, zh: /下载或先解码/, ja: /ダウンロードまたはデコード/, es: /descargado o decodificado/, de: /heruntergeladen oder dekodiert/, fr: /téléchargé ou décodé/ },
    heldRemote: { en: /another machine/, zh: /另一台机器/, ja: /別のマシン/, es: /otra máquina/, de: /anderen Maschine/, fr: /autre machine/ },
  } as Record<MessageKey, Record<(typeof LANGS)[number], RegExp>>;

  it.each(LANGS)('%s: each held line is about its own kind and none of the others', (lang) => {
    for (const [key, byLang] of Object.entries(TOPIC)) {
      for (const [other, otherByLang] of Object.entries(TOPIC)) {
        const line = MESSAGES[lang][key as MessageKey] as string;
        if (other === key) expect(line, `${lang}.${key}`).toMatch(otherByLang[lang]);
        else expect(line, `${lang}.${key} must not be about ${other}`).not.toMatch(otherByLang[lang]);
      }
      expect(byLang[lang]).toBeInstanceOf(RegExp);
    }
  });

  it('the guard itself: the old line is the delete / send / pay one', () => {
    expect(MESSAGES.en.riskyNote).toMatch(/delete, send or pay/);
    for (const key of KEYS) expect(MESSAGES.en[key]).not.toMatch(/delete, send or pay/);
  });
});

describe('what the island prints under a held card, one kind at a time, in six languages', () => {
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

  const CASES: [string, string, PendingCard][] = [
    ['takeover', 'heldTakeover', action('takeover', { kind: 'desktop_takeover', target: '5 min · tidy the desktop', options: ['once'] })],
    ['outside', 'heldOutside', card({ type: 'propose_run_command', pretty: 'mv a b', perm_kind: 'outside', sandbox: 'outside' })],
    ['system', 'heldSystem', card({ type: 'propose_run_command', pretty: 'defaults write com.apple.dock autohide -bool true', perm_kind: 'system' })],
    ['capability', 'heldCapability', card({ type: 'propose_action', kind: 'capability', target: 'Add srv?', detail: '', perm_kind: 'capability' })],
    ['other_agent', 'heldOtherAgent', card({ type: 'propose_action', kind: 'other_agent', target: 'Change Codex settings?', detail: '', perm_kind: 'other_agent' })],
    ['opaque', 'heldOpaque', card({ type: 'propose_run_command', pretty: 'curl x | sh', perm_kind: 'opaque' })],
    ['remote', 'heldRemote', card({ type: 'propose_run_command', pretty: 'ls', remote_host: 'mini', perm_kind: 'remote' })],
    ['money', 'riskyNote', action('money', { kind: 'desktop_risky', target: 'Shop · Pay' })],
    ['send', 'riskyNote', action('send', { kind: 'desktop_risky', target: 'Mail · Send' })],
    ['destructive', 'riskyNote', card({ type: 'propose_run_command', pretty: 'rm old.txt', perm_kind: 'destructive' })],
    ['app_risky', 'riskyNote', action('app_risky', { kind: 'desktop_risky', target: 'Notes · Delete' })],
    ['an unknown kind', 'heldGeneric', action('made_up', { kind: 'made_up', target: 'x' })],
  ];

  for (const lang of LANGS) {
    it.each(CASES)(`${lang}: a %s card says its own line, and offers Open in Arslan, not Allow`, async (_what, key, held) => {
      await mount(held, lang);
      expect(screen.getByTestId('island-risky')).toHaveTextContent(islandText(lang, key as MessageKey));
      expect(screen.getByTestId('island-risky').textContent).toBe(islandText(lang, key as MessageKey));
      expect(screen.queryByTestId('island-allow')).toBeNull();
      expect(screen.getByTestId('island-open-in-arslan')).toBeInTheDocument();
    });
  }

  it('a card the island may answer carries no note at all', async () => {
    await mount({ ...action('app'), island_ok: true }, 'en');
    expect(screen.queryByTestId('island-risky')).toBeNull();
    expect(screen.getByTestId('island-allow')).toBeInTheDocument();
  });
});

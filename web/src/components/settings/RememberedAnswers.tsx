import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AppWindow, CalendarClock, Folder, Globe, Info, KeyRound, Plug, Terminal, Zap, type LucideIcon } from 'lucide-react';
import { ApiError, request } from '../../api/client';
import { formatUiTime, uiDate, uiLocale } from '../../lib/localeFormatting';
import { Escaped, isolate } from '../../lib/outsideText';

/** One row of GET /permissions/rules: an "Always" (only apps have one today). */
export interface RememberedRule {
  id: number; kind: string; target: string; label: string;
  created_at: string | null; last_used_at: string | null; use_count: number;
}

/** One row of GET /permissions/grants (S4a, S6): an "In this conversation" yes, and the block it is listed under. */
export interface RememberedGrant {
  id: number; conversation_id: string; title: string; kind: string; target: string; created_at: string | null;
  /** The kind as the page words it (`server/api/permissions.py` `_what`). */
  what: string; name: string; server: string; server_gone: boolean;
  sub_session: boolean; parent_id: string; parent_title: string;
}

/** Each kind of grant: its icon, whether its name is shown as code (commands, sites, folders), its "only when…"
 *  note, and the amber edge of the two that let commands out of the sandbox. */
const KINDS: Record<string, { icon: LucideIcon; mono?: boolean; note?: string; wide?: boolean }> = {
  outside: { icon: Terminal, wide: true },
  unsandboxed: { icon: Terminal, wide: true, note: 'unsandboxed' },
  command: { icon: Terminal, mono: true, note: 'command' },
  network: { icon: Globe, note: 'network' },
  workspace_write: { icon: Folder, mono: true },
  schedule: { icon: CalendarClock },
  mcp_tool: { icon: Plug },
  app: { icon: AppWindow },
  site: { icon: Globe, mono: true },
  shortcut: { icon: Zap },
  other: { icon: KeyRound, mono: true },
};
/** How long a taken-back row takes to fade out before it leaves. */
export const FADE_MS = 200;

type Listed<T> = T[] | 'failed' | null;
type RowState = 'busy' | 'failed' | 'leaving';

/** "Today 14:20", "yesterday", or "3 November": when an answer was given or last used. */
function when(iso: string | null, language: string): string {
  if (!iso) return '';
  const date = uiDate(iso);
  if (Number.isNaN(date.getTime())) return '';
  const lang = uiLocale(language);
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(new Date()) - day(date)) / 86_400_000);
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
  if (days === 0) return `${rtf.format(0, 'day')} ${formatUiTime(date, lang)}`;
  if (days === 1) return rtf.format(-1, 'day');
  return date.toLocaleDateString(lang, {
    month: 'long', day: 'numeric', ...(date.getFullYear() !== new Date().getFullYear() ? { year: 'numeric' } : {}) });
}

/** The sentence, with the command, site or folder in it set as code (cut to one line, the whole on hover). */
function Sentence({ text, code, full }: { text: string; code?: string; full?: string }) {
  const at = code ? text.indexOf(code) : -1;
  if (!code || at < 0) return <>{text}</>;
  return <>{text.slice(0, at)}<code data-testid="remembered-code" title={isolate(full || code)}
    className="inline-block max-w-[18rem] truncate align-bottom font-mono text-[12px] text-foreground"><Escaped text={code} /></code>
    {text.slice(at + code.length)}</>;
}

/**
 * S6 (v0.1.64): "Remembered answers", the last group of Settings › What Arslan may do. Every "Always" (apps) and every
 * "In this conversation" yes, by conversation, newest first, a sub-session's under its commander, each taken back with
 * one click and no confirm: the worst a take-back does is ask once more. It replaced the old terminal-rules list and the
 * outside-the-sandbox list. Nothing is added here. S4b's allowed folders add their own section below "In this
 * conversation" when they exist.
 */
export default function RememberedAnswers({ titles = {}, onOpenConversation, onLoaded }: {
  /** The sidebar's own titles (generated, kept by the window), which win over the server's first message. */
  titles?: Record<string, string>;
  onOpenConversation?: (conversationId: string) => void;
  /** Both lists have been read (or failed) and drawn: a deep link scrolls here again (SettingsScreen). */
  onLoaded?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n?.language ?? 'en';
  const [rules, setRules] = useState<Listed<RememberedRule>>(null);
  const [grants, setGrants] = useState<Listed<RememberedGrant>>(null);
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const list = <T,>(path: string, set: (v: Listed<T>) => void) => request<T[]>(path)
      .then((body) => { if (alive.current) set(Array.isArray(body) ? body : 'failed'); })
      .catch(() => { if (alive.current) set('failed'); });
    void list<RememberedRule>('/permissions/rules', setRules);
    void list<RememberedGrant>('/permissions/grants', setGrants);
    return () => { alive.current = false; };
  }, []);
  const loaded = rules !== null && grants !== null;
  const told = useRef(false);
  useEffect(() => {
    if (loaded && !told.current) { told.current = true; onLoaded?.(); }
  }, [loaded, onLoaded]);

  const mark = (key: string, state: RowState | null) => setRows((r) => {
    const next = { ...r };
    if (state) next[key] = state; else delete next[key];
    return next;
  });

  /** Takes one back. Gone already (404) counts as taken back; any other failure keeps the row for a retry. */
  const revoke = useCallback(async (type: 'rule' | 'grant', id: number) => {
    const key = `${type}:${id}`;
    mark(key, 'busy');
    try {
      await request(`/permissions/${type}s/${id}`, { method: 'DELETE' });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) { if (alive.current) mark(key, 'failed'); return; }
    }
    if (!alive.current) return;
    mark(key, 'leaving');
    setTimeout(() => {
      if (!alive.current) return;
      if (type === 'rule') setRules((l) => Array.isArray(l) ? l.filter((r) => r.id !== id) : l);
      else setGrants((l) => Array.isArray(l) ? l.filter((g) => g.id !== id) : l);
      mark(key, null);
    }, FADE_MS);
  }, []);

  const row = (key: string, icon: LucideIcon, sentence: ReactNode, middle: ReactNode[], opts: {
    type: 'rule' | 'grant'; id: number; what: string; wide?: boolean; note?: string }) => {
    const state = rows[key];
    const Icon = icon;
    return (
      <li key={key} data-testid="remembered-row" data-what={opts.what} data-state={state ?? 'shown'}
        className={`flex flex-col gap-1 border-l-2 py-2 pl-3 transition-opacity duration-200 sm:flex-row sm:items-start sm:gap-4 ${
          opts.wide ? 'border-warning' : 'border-transparent'} ${state === 'leaving' ? 'opacity-0' : 'opacity-100'}`}>
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0">
            <p data-testid="remembered-sentence" className="text-[13px] leading-snug text-foreground">{sentence}</p>
            {opts.note && <p data-testid="remembered-note" className="text-[12px] text-subtle-foreground">{opts.note}</p>}
            {state === 'failed' && <p data-testid="remembered-failed" className="text-[12px] text-danger">{t('remembered.revokeFailed')}</p>}
          </div>
        </div>
        <div className="flex shrink-0 flex-col pl-5 text-[12px] text-subtle-foreground sm:w-48 sm:pl-0">
          {middle.filter(Boolean).map((line, i) => <span key={i}>{line}</span>)}
        </div>
        <button type="button" data-testid="remembered-revoke" disabled={state === 'busy' || state === 'leaving'}
          onClick={() => void revoke(opts.type, opts.id)}
          className="ml-5 shrink-0 self-start rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground disabled:cursor-default disabled:opacity-40 sm:ml-0">
          {t('remembered.revoke')}
        </button>
      </li>
    );
  };

  const grantRow = (g: RememberedGrant) => {
    const kind = KINDS[g.what] ?? KINDS.other;
    const name = g.name || g.target;
    const text = t(`remembered.grant.${KINDS[g.what] ? g.what : 'other'}`, { name, server: g.server || 'MCP' });
    const note = g.what === 'mcp_tool' && g.server_gone ? t('remembered.note.serverGone')
      : kind.note ? t(`remembered.note.${kind.note}`) : undefined;
    return row(`grant:${g.id}`, kind.icon, <Sentence text={text} code={kind.mono ? name : undefined}
      full={g.what === 'workspace_write' ? g.target : name} />,
      [g.sub_session ? t('remembered.subOnly') : '', g.created_at ? t('remembered.given', { when: when(g.created_at, lang) }) : ''],
      { type: 'grant', id: g.id, what: g.what, wide: kind.wide, note });
  };

  const ruleRow = (r: RememberedRule) => {
    const name = r.label || r.target;
    return row(`rule:${r.id}`, r.kind === 'app' ? AppWindow : KeyRound,
      t(r.kind === 'app' ? 'remembered.rule.app' : 'remembered.rule.other', { name }),
      [t('remembered.allConversations'), r.created_at ? t('remembered.given', { when: when(r.created_at, lang) }) : '',
        r.last_used_at ? t('remembered.lastUsed', { when: when(r.last_used_at, lang), count: r.use_count })
          : t('remembered.neverUsed')],
      { type: 'rule', id: r.id, what: r.kind });
  };

  // By conversation, newest first (the list comes newest first); a sub-session's grants under its commander's block.
  const blocks: { id: string; title: string; own: RememberedGrant[]; subs: Map<string, RememberedGrant[]> }[] = [];
  for (const g of Array.isArray(grants) ? grants : []) {
    let block = blocks.find((b) => b.id === g.parent_id);
    if (!block) {
      block = { id: g.parent_id, title: titles[g.parent_id] || g.parent_title, own: [], subs: new Map() };
      blocks.push(block);
    }
    if (g.sub_session) block.subs.set(g.conversation_id, [...(block.subs.get(g.conversation_id) ?? []), g]);
    else block.own.push(g);
  }
  const blockGrants = (b: (typeof blocks)[number]) => [...b.own, ...[...b.subs.values()].flat()];

  const empty = <p className="text-[12px] text-subtle-foreground">{t('remembered.none')}</p>;
  const failed = <p data-testid="remembered-unavailable" className="text-[12px] text-subtle-foreground">{t('remembered.unavailable')}</p>;
  const section = (title: string, testId: string, body: ReactNode) => (
    <section data-testid={testId} className="flex flex-col gap-1">
      <h4 className="text-[12px] font-semibold text-muted-foreground">{title}</h4>
      {body}
    </section>
  );
  const nothing = Array.isArray(rules) && Array.isArray(grants) && rules.length === 0 && grants.length === 0;
  const neither = rules === 'failed' && grants === 'failed';

  return (
    <div data-testid="remembered-answers" className="flex flex-col gap-4">
      <p className="text-[12px] leading-snug text-muted-foreground">{t('remembered.desc')}</p>
      <p data-testid="remembered-never" className="flex items-start gap-2 rounded-lg bg-fill px-3 py-2 text-[12px] leading-snug text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />{t('remembered.never')}
      </p>
      {neither ? failed : nothing ? <p data-testid="remembered-empty" className="text-[12px] text-subtle-foreground">{t('remembered.empty')}</p> : <>
        {rules !== null && section(t('remembered.always'), 'remembered-always', rules === 'failed' ? failed
          : rules.length ? <ul className="flex flex-col">{rules.map(ruleRow)}</ul> : empty)}
        {grants !== null && section(t('remembered.conversation'), 'remembered-conversation', grants === 'failed' ? failed
          : blocks.length ? blocks.map((b) => (
            <div key={b.id} data-testid="remembered-block" className="flex flex-col rounded-lg border border-border/60 px-3 py-2">
              <div className="flex items-center gap-3">
                <span data-testid="remembered-block-title" className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground"
                  title={isolate(b.title || t('remembered.untitled'))}><Escaped text={b.title || t('remembered.untitled')} /></span>
                {onOpenConversation && <button type="button" data-testid="remembered-open" onClick={() => onOpenConversation(b.id)}
                  className="shrink-0 text-[12px] text-primary hover:underline">{t('remembered.open')}</button>}
                <button type="button" data-testid="remembered-revoke-all"
                  onClick={() => { for (const g of blockGrants(b)) void revoke('grant', g.id); }}
                  className="shrink-0 text-[12px] text-muted-foreground hover:text-foreground">{t('remembered.revokeAll')}</button>
              </div>
              {b.own.length > 0 && <ul className="flex flex-col">{b.own.map(grantRow)}</ul>}
              {[...b.subs.entries()].map(([sub, list]) => (
                <div key={sub} data-testid="remembered-sub" className="ml-4 mt-1 flex flex-col">
                  <span className="truncate text-[12px] text-muted-foreground">
                    {t('remembered.subSession', { title: titles[sub] || list[0].title || t('remembered.untitled') })}</span>
                  <ul className="flex flex-col">{list.map(grantRow)}</ul>
                </div>
              ))}
            </div>
          )) : empty)}
        {/* S4b: its allowed folders get their own section here, below "In this conversation". */}
      </>}
    </div>
  );
}

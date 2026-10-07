import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';
import { proactiveApi, type ProactiveWatch } from '../../api/proactive';
import { formatRelativeTime } from '../settings/relativeTime';
import { proactiveErrorText } from '../../lib/proactive';
import { confirmSheet } from '../kit';

/** Intervals a watch may use, in seconds. The backend bounds it to 30 min – 7 days; these are the ones offered. */
export const WATCH_INTERVALS = [1800, 3600, 21600, 43200, 86400, 604800];
const field = 'rounded-lg border border-border bg-background px-2 py-1 text-xs text-foreground';
const divider = <div className="h-[1px] bg-border/40" />;

export function muteLabel(t: (k: string, o?: Record<string, unknown>) => string, key: string): string {
  if (key.startsWith('kind:')) return t('proactive.settings.muteKind', { kind: t(`proactive.kind.${key.slice(5)}`) });
  if (key.startsWith('watch:')) return t('proactive.settings.muteSource', { id: key.slice(6) });
  return t('proactive.settings.muteOther');
}

/**
 * What Arslan watches for you (web pages, folders) and what it no longer reminds you of
 * (0.1.55 §12: managed in the Inbox — "正在盯着" / "不再提醒"; Settings links here).
 * Self-loading; `watchesOn` false shows that watching is switched off in Settings.
 */
export default function WatchesPanel({ watchesOn = true, quiet = false }: { watchesOn?: boolean; quiet?: boolean }) {
  const { t } = useTranslation();
  const [watches, setWatches] = useState<ProactiveWatch[]>([]);
  const [mutes, setMutes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ kind: 'web' as 'web' | 'folder', target: '', label: '', interval_s: 21600, notify: true });
  const fail = useCallback((cause: unknown) => setError(proactiveErrorText(t, 'settings', cause)), [t]);
  const reload = useCallback(async () => {
    try {
      const [w, m] = await Promise.all([proactiveApi.watches(), proactiveApi.mutes()]);
      setWatches(w.watches); setMutes(m.mutes);
    } catch (cause) { fail(cause); }
  }, [fail]);
  useEffect(() => { void reload(); }, [reload]);
  async function run(operation: () => Promise<unknown>) {
    setError(null);
    try { await operation(); await reload(); } catch (cause) { fail(cause); }
  }
  async function addWatch(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      await proactiveApi.addWatch({ kind: draft.kind, target: draft.target.trim(), ...(draft.label.trim() ? { label: draft.label.trim() } : {}),
        interval_s: draft.interval_s, notify: draft.notify });
      setDraft((d) => ({ ...d, target: '', label: '' }));
      setAdding(false);
    });
  }
  return (
    <div className="space-y-5" data-testid="watches-panel">
      {/* In the Inbox (quiet) a failure hides nothing else and raises no alert of its own. */}
      {error && !quiet && <p role="alert" className="text-[11px] text-danger-strong">{error}</p>}
        <div data-testid="proactive-watches" className="space-y-3">
          {!quiet && <div><h4 className="text-xs font-bold text-foreground font-sans">{t('proactive.settings.watchesTitle')}</h4>
            <p className="text-[11px] text-muted-foreground mt-0.5 max-w-xl">{t('proactive.settings.watchesDesc')}</p></div>}
          {watches.length > 0 && !watchesOn && <p data-testid="proactive-watches-off" role="status"
            className="text-[11px] text-warning max-w-xl">{t('proactive.settings.watchesOff')}</p>}
          {watches.length === 0 && <p className="text-xs text-muted-foreground">{t('proactive.settings.noWatches')}</p>}
          <ul className="space-y-2">{watches.map((w) => <li key={w.id} data-testid={`proactive-watch-${w.id}`} className="rounded-xl border border-border bg-surface p-3 text-xs">
            <p className="truncate font-medium" title={w.label}>{w.label}</p>
            <p className="truncate text-[11px] text-muted-foreground" title={w.target}>{w.target}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {w.last_checked_at ? t('proactive.settings.lastChecked', { when: formatRelativeTime(w.last_checked_at, t) }) : t('proactive.settings.neverChecked')}
              {w.last_changed_at && <> · {t('proactive.settings.lastChange', { when: formatRelativeTime(w.last_changed_at, t) })}</>}
            </p>
            {w.last_error && <p className="mt-1 break-words text-[11px] text-danger-strong">{t('proactive.settings.unreadable', { error: w.last_error })}</p>}
            {/* 0.1.55: controls under the text, so the same row fits Settings and the Inbox's rail. */}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select aria-label={t('proactive.settings.every')} className={field} value={w.interval_s} onChange={(e) => void run(() => proactiveApi.updateWatch(w.id, { interval_s: Number(e.target.value) }))}>
                {(WATCH_INTERVALS.includes(w.interval_s) ? WATCH_INTERVALS : [...WATCH_INTERVALS, w.interval_s].sort((a, b) => a - b)).map((s) =>
                  <option key={s} value={s}>{t(`proactive.settings.intervals.${s}`, { defaultValue: `${Math.round(s / 60)} min` })}</option>)}</select>
              <label className="flex items-center gap-1"><input type="checkbox" checked={w.notify} onChange={(e) => void run(() => proactiveApi.updateWatch(w.id, { notify: e.target.checked }))} />{t('proactive.settings.notifyThis')}</label>
              <span className="flex-1" />
              <button type="button" className="rounded-lg bg-fill px-2 py-1 hover:bg-fill-strong" onClick={() => void run(() => proactiveApi.updateWatch(w.id, { enabled: !w.enabled }))}>
                {t(w.enabled ? 'proactive.settings.pause' : 'proactive.settings.resume')}</button>
              <button type="button" aria-label={t('proactive.settings.remove')} title={t('proactive.settings.remove')} className="rounded-lg bg-fill p-1.5 text-muted-foreground hover:text-danger-strong"
                onClick={() => void (async () => {
                  // 0.1.55: removing a watch also drops its history; it asks first.
                  if (await confirmSheet({ title: t('proactive.settings.removeTitle', { label: w.label }), body: t('proactive.settings.removeBody'),
                    action: t('proactive.settings.remove') })) await run(() => proactiveApi.deleteWatch(w.id));
                })()}><Trash2 size={13} /></button>
            </div>
          </li>)}</ul>
          {quiet && !adding ? <button type="button" data-testid="watch-add-open" onClick={() => setAdding(true)}
            className="flex h-9 w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-border text-[13px] text-muted-foreground hover:text-foreground">
            <Plus size={14} />{t('inbox.addWatch')}</button> : (
          <form onSubmit={(e) => void addWatch(e)} className="flex flex-wrap items-end gap-2 rounded-xl border border-dashed border-border p-3 text-xs" data-testid="proactive-add-watch">
            <label className="flex flex-col gap-1">{t('proactive.settings.type')}
              <select className={field} value={draft.kind} onChange={(e) => setDraft((d) => ({ ...d, kind: e.target.value as 'web' | 'folder' }))}>
                <option value="web">{t('proactive.settings.addWeb')}</option><option value="folder">{t('proactive.settings.addFolder')}</option></select></label>
            <label className="flex min-w-40 flex-1 flex-col gap-1">{t('proactive.settings.target')}
              <input required className={field} value={draft.target} maxLength={4000} placeholder={t(draft.kind === 'web' ? 'proactive.settings.targetWeb' : 'proactive.settings.targetFolder')}
                onChange={(e) => setDraft((d) => ({ ...d, target: e.target.value }))} /></label>
            <label className="flex flex-col gap-1">{t('proactive.settings.label')}
              <input className={field} value={draft.label} maxLength={120} onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} /></label>
            <label className="flex flex-col gap-1">{t('proactive.settings.every')}
              <select className={field} value={draft.interval_s} onChange={(e) => setDraft((d) => ({ ...d, interval_s: Number(e.target.value) }))}>
                {WATCH_INTERVALS.map((s) => <option key={s} value={s}>{t(`proactive.settings.intervals.${s}`)}</option>)}</select></label>
            <label className="flex items-center gap-1 pb-1"><input type="checkbox" checked={draft.notify} onChange={(e) => setDraft((d) => ({ ...d, notify: e.target.checked }))} />{t('proactive.settings.notifyThis')}</label>
            <button className="inline-flex items-center gap-1 rounded-lg bg-foreground px-3 py-1.5 font-semibold text-background disabled:opacity-50" disabled={!draft.target.trim()}><Plus size={13} />{t('proactive.settings.add')}</button>
          </form>
          )}
          <p className="text-[11px] text-muted-foreground max-w-xl">{t('proactive.settings.webNote')}</p>
        </div>
        {divider}
        <div data-testid="proactive-mutes" className="space-y-2">
          <h4 className="text-xs font-bold text-foreground font-sans">{t('proactive.settings.muted')}</h4>
          {mutes.length === 0 && <p className="text-xs text-muted-foreground">{t('proactive.settings.mutedNone')}</p>}
          <ul className="space-y-1">{mutes.map((key) => <li key={key} className="flex items-center justify-between gap-3 text-xs">
            <span>{muteLabel(t, key)}</span>
            <button type="button" className="rounded-lg border border-border px-2 py-1 hover:bg-foreground/5" onClick={() => void run(() => proactiveApi.unmute(key))}>{t('proactive.settings.unmute')}</button></li>)}</ul>
        </div>
    </div>
  );
}

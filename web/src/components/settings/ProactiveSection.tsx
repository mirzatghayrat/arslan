import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BellRing, Plus, Trash2 } from 'lucide-react';
import { proactiveApi, type ProactiveConfig, type ProactiveWatch } from '../../api/proactive';
import { formatRelativeTime } from './relativeTime';
import { proactiveErrorText } from '../../lib/proactive';

/** Intervals a watch may use, in seconds. The backend bounds it to 30 min – 7 days; these are the
 * ones offered. */
export const WATCH_INTERVALS = [1800, 3600, 21600, 43200, 86400, 604800];
const CAPS = [1, 2, 3, 5, 10, 20];
const field = 'rounded-lg border border-border bg-background px-2 py-1 text-xs text-foreground';
const divider = <div className="h-[1px] bg-border/40" />;

function Toggle({ id, label, desc, checked, onChange }: { id: string; label: string; desc?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <div className="flex items-start justify-between gap-4">
    <div><h4 className="text-xs font-bold text-foreground font-sans">{label}</h4>
      {desc && <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{desc}</p>}</div>
    <input id={id} data-testid={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
      className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer" />
  </div>;
}

function muteLabel(t: (k: string, o?: Record<string, unknown>) => string, key: string): string {
  if (key.startsWith('kind:')) return t('proactive.settings.muteKind', { kind: t(`proactive.kind.${key.slice(5)}`) });
  if (key.startsWith('watch:')) return t('proactive.settings.muteSource', { id: key.slice(6) });
  return t('proactive.settings.muteOther');
}

/**
 * Proactivity: what Arslan looks out for and how it tells you. Everything here is free (the
 * one control that spends, the cause-guessing limit, lives in Automation with the other
 * spenders). Changes save as they are made: a toggle that waited for a Save button would leave
 * "look out for things" looking on while the loop still saw the old value.
 */
export default function ProactiveSection() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<ProactiveConfig | null>(null);
  const [watches, setWatches] = useState<ProactiveWatch[]>([]);
  const [mutes, setMutes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ kind: 'web' as 'web' | 'folder', target: '', label: '', interval_s: 21600, notify: true });
  const fail = useCallback((cause: unknown) => setError(proactiveErrorText(t, 'settings', cause)), [t]);

  const reload = useCallback(async () => {
    try {
      const [c, w, m] = await Promise.all([proactiveApi.config(), proactiveApi.watches(), proactiveApi.mutes()]);
      setConfig(c); setWatches(w.watches); setMutes(m.mutes);
    } catch (cause) { fail(cause); }
  }, [fail]);
  useEffect(() => { void reload(); }, [reload]);

  async function save(patch: Partial<ProactiveConfig>) {
    const before = config;
    setConfig((c) => (c ? { ...c, ...patch } : c)); setError(null);
    try { setConfig(await proactiveApi.saveConfig(patch)); }
    catch (cause) { setConfig(before); fail(cause); }
  }
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
    });
  }

  if (!config) return <div className="bg-surface border border-border rounded-2xl p-6" data-testid="settings-proactive">
    {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : <p role="status" className="text-xs text-muted-foreground">{t('companion.loading')}</p>}
  </div>;

  const caps = CAPS.includes(config.notify_daily_cap) ? CAPS : [...CAPS, config.notify_daily_cap].sort((a, b) => a - b);
  const sources: [keyof ProactiveConfig, string][] = [['job_followups', 'jobFollowups'], ['scheduled_problems', 'scheduledProblems'], ['watches', 'watches']];
  return (
    <div className="bg-surface border border-border rounded-2xl p-6" data-testid="settings-proactive">
      <div className="flex items-center gap-2 mb-1">
        <BellRing className="w-3.5 h-3.5 text-subtle-foreground" aria-hidden />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('proactive.settings.title')}</h3>
      </div>
      <p className="text-[11px] text-muted-foreground font-sans max-w-2xl mb-5">{t('proactive.settings.lede')}</p>
      {error && <p role="alert" className="mb-4 text-[11px] text-destructive">{error}</p>}
      <div className="space-y-5">
        <Toggle id="proactive-toggle-enabled" label={t('proactive.settings.enabled')} desc={t('proactive.settings.enabledDesc')}
          checked={config.enabled} onChange={(v) => void save({ enabled: v })} />
        <fieldset className="space-y-3" disabled={!config.enabled}>
          <legend className="text-[11px] font-mono uppercase tracking-widest text-muted-foreground mb-2">{t('proactive.settings.sources')}</legend>
          {sources.map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs">
            <input type="checkbox" data-testid={`proactive-source-${key}`} checked={Boolean(config[key])} onChange={(e) => void save({ [key]: e.target.checked } as Partial<ProactiveConfig>)}
              className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0" />{t(`proactive.settings.${label}`)}</label>)}
        </fieldset>
        {divider}
        <Toggle id="proactive-toggle-notify" label={t('proactive.settings.notify')} desc={t('proactive.settings.notifyDesc')}
          checked={config.notify} onChange={(v) => void save({ notify: v })} />
        <div className="space-y-3 text-xs" aria-disabled={!config.notify}>
          <select aria-label={t('proactive.settings.notify')} data-testid="proactive-notify-cap" className={field} disabled={!config.notify} value={config.notify_daily_cap}
            onChange={(e) => void save({ notify_daily_cap: Number(e.target.value) })}>{caps.map((n) => <option key={n} value={n}>{t('proactive.settings.notifyCap', { n })}</option>)}</select>
          {/* One unit that wraps as a whole: "Quiet hours  From [..]  To [..]" never splits mid-range. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="font-bold text-foreground">{t('proactive.settings.quiet')}</span>
            <span className="flex items-center gap-2 whitespace-nowrap">
              <label className="flex items-center gap-2">{t('proactive.settings.from')}
                <input type="time" data-testid="proactive-quiet-start" className={field} value={config.quiet_start} onChange={(e) => e.target.value && void save({ quiet_start: e.target.value })} /></label>
              <label className="flex items-center gap-2">{t('proactive.settings.to')}
                <input type="time" data-testid="proactive-quiet-end" className={field} value={config.quiet_end} onChange={(e) => e.target.value && void save({ quiet_end: e.target.value })} /></label>
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground max-w-xl">{t('proactive.settings.quietDesc')}</p>
        </div>
        {divider}
        <Toggle id="proactive-toggle-brief" label={t('proactive.settings.brief')} desc={t('proactive.settings.briefDesc')}
          checked={config.brief_enabled} onChange={(v) => void save({ brief_enabled: v })} />
        {config.brief_enabled && <label className="flex items-center gap-2 text-xs">{t('proactive.settings.briefAt')}
          <input type="time" data-testid="proactive-brief-time" className={field} value={config.brief_time} onChange={(e) => e.target.value && void save({ brief_time: e.target.value })} /></label>}
        <p className="text-[11px] text-muted-foreground max-w-xl">{t('proactive.settings.diagnosisPointer')}</p>
        {divider}
        <div data-testid="proactive-watches" className="space-y-3">
          <div><h4 className="text-xs font-bold text-foreground font-sans">{t('proactive.settings.watchesTitle')}</h4>
            <p className="text-[11px] text-muted-foreground mt-0.5 max-w-xl">{t('proactive.settings.watchesDesc')}</p></div>
          {watches.length > 0 && !(config.enabled && config.watches) && <p data-testid="proactive-watches-off" role="status"
            className="text-[11px] text-warning max-w-xl">{t('proactive.settings.watchesOff')}</p>}
          {watches.length === 0 && <p className="text-xs text-muted-foreground">{t('proactive.settings.noWatches')}</p>}
          <ul className="space-y-2">{watches.map((w) => <li key={w.id} data-testid={`proactive-watch-${w.id}`} className="rounded-lg border border-border p-3 text-xs">
            <div className="flex items-start gap-3"><div className="min-w-0 flex-1">
              <p className="font-medium break-words">{w.label}</p>
              <p className="break-all text-[11px] text-muted-foreground">{w.target}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {w.last_checked_at ? t('proactive.settings.lastChecked', { when: formatRelativeTime(w.last_checked_at, t) }) : t('proactive.settings.neverChecked')}
                {w.last_changed_at && <> · {t('proactive.settings.lastChange', { when: formatRelativeTime(w.last_changed_at, t) })}</>}
              </p>
              {w.last_error && <p className="mt-1 text-[11px] text-destructive break-words">{t('proactive.settings.unreadable', { error: w.last_error })}</p>}
            </div>
              <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                <select aria-label={t('proactive.settings.every')} className={field} value={w.interval_s} onChange={(e) => void run(() => proactiveApi.updateWatch(w.id, { interval_s: Number(e.target.value) }))}>
                  {(WATCH_INTERVALS.includes(w.interval_s) ? WATCH_INTERVALS : [...WATCH_INTERVALS, w.interval_s].sort((a, b) => a - b)).map((s) =>
                    <option key={s} value={s}>{t(`proactive.settings.intervals.${s}`, { defaultValue: `${Math.round(s / 60)} min` })}</option>)}</select>
                <label className="flex items-center gap-1"><input type="checkbox" checked={w.notify} onChange={(e) => void run(() => proactiveApi.updateWatch(w.id, { notify: e.target.checked }))} />{t('proactive.settings.notifyThis')}</label>
                <button type="button" className="rounded-lg border border-border px-2 py-1 hover:bg-foreground/5" onClick={() => void run(() => proactiveApi.updateWatch(w.id, { enabled: !w.enabled }))}>
                  {t(w.enabled ? 'proactive.settings.pause' : 'proactive.settings.resume')}</button>
                <button type="button" aria-label={t('proactive.settings.remove')} title={t('proactive.settings.remove')} className="rounded-lg border border-border p-1.5 text-muted-foreground hover:text-destructive" onClick={() => void run(() => proactiveApi.deleteWatch(w.id))}><Trash2 size={13} /></button>
              </div></div>
          </li>)}</ul>
          <form onSubmit={(e) => void addWatch(e)} className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border p-3 text-xs" data-testid="proactive-add-watch">
            <label className="flex flex-col gap-1">{t('proactive.settings.type')}
              <select className={field} value={draft.kind} onChange={(e) => setDraft((d) => ({ ...d, kind: e.target.value as 'web' | 'folder' }))}>
                <option value="web">{t('proactive.settings.addWeb')}</option><option value="folder">{t('proactive.settings.addFolder')}</option></select></label>
            <label className="flex min-w-48 flex-1 flex-col gap-1">{t('proactive.settings.target')}
              <input required className={field} value={draft.target} maxLength={4000} placeholder={t(draft.kind === 'web' ? 'proactive.settings.targetWeb' : 'proactive.settings.targetFolder')}
                onChange={(e) => setDraft((d) => ({ ...d, target: e.target.value }))} /></label>
            <label className="flex flex-col gap-1">{t('proactive.settings.label')}
              <input className={field} value={draft.label} maxLength={120} onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} /></label>
            <label className="flex flex-col gap-1">{t('proactive.settings.every')}
              <select className={field} value={draft.interval_s} onChange={(e) => setDraft((d) => ({ ...d, interval_s: Number(e.target.value) }))}>
                {WATCH_INTERVALS.map((s) => <option key={s} value={s}>{t(`proactive.settings.intervals.${s}`)}</option>)}</select></label>
            <label className="flex items-center gap-1 pb-1"><input type="checkbox" checked={draft.notify} onChange={(e) => setDraft((d) => ({ ...d, notify: e.target.checked }))} />{t('proactive.settings.notifyThis')}</label>
            <button className="inline-flex items-center gap-1 rounded-lg border border-border bg-primary px-3 py-1.5 text-primary-foreground disabled:opacity-50" disabled={!draft.target.trim()}><Plus size={13} />{t('proactive.settings.add')}</button>
          </form>
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
    </div>
  );
}

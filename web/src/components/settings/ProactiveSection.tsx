import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BellRing } from 'lucide-react';
import { proactiveApi, type ProactiveConfig } from '../../api/proactive';
import WatchesPanel from '../proactive/WatchesPanel';
import { proactiveErrorText } from '../../lib/proactive';

export { WATCH_INTERVALS } from '../proactive/WatchesPanel';
const CAPS = [1, 2, 3, 5, 10, 20];
const field = 'rounded-lg border border-border bg-background px-2 py-1 text-xs text-foreground';
const divider = <div className="h-[1px] bg-border/40" />;

function Toggle({ id, label, desc, checked, onChange }: { id: string; label: string; desc?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <div className="flex items-start justify-between gap-4">
    <div><h4 className="text-[13px] font-medium text-foreground">{label}</h4>
      {desc && <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">{desc}</p>}</div>
    <input id={id} data-testid={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
      className="kit-switch mt-0.5" />
  </div>;
}


/**
 * Proactivity: what Arslan looks out for and how it tells you. Everything here is free (the
 * one control that spends, the cause-guessing limit, lives in Automation with the other
 * spenders). Changes save as they are made: a toggle that waited for a Save button would leave
 * "look out for things" looking on while the loop still saw the old value.
 */
export type ProactiveBlock = 'looking' | 'notify' | 'brief' | 'watches';

export default function ProactiveSection({ only, bare = false }: { only?: ProactiveBlock[]; bare?: boolean } = {}) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<ProactiveConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = useCallback((cause: unknown) => setError(proactiveErrorText(t, 'settings', cause)), [t]);

  const reload = useCallback(async () => {
    try {
      setConfig(await proactiveApi.config());
    } catch (cause) { fail(cause); }
  }, [fail]);
  useEffect(() => { void reload(); }, [reload]);

  async function save(patch: Partial<ProactiveConfig>) {
    const before = config;
    setConfig((c) => (c ? { ...c, ...patch } : c)); setError(null);
    try { setConfig(await proactiveApi.saveConfig(patch)); }
    catch (cause) { setConfig(before); fail(cause); }
  }

  if (!config) return <div className="bg-surface border border-border rounded-2xl p-6" data-testid="settings-proactive">
    {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : <p role="status" className="text-xs text-muted-foreground">{t('companion.loading')}</p>}
  </div>;

  const caps = CAPS.includes(config.notify_daily_cap) ? CAPS : [...CAPS, config.notify_daily_cap].sort((a, b) => a - b);
  const sources: [keyof ProactiveConfig, string][] = [['job_followups', 'jobFollowups'], ['scheduled_problems', 'scheduledProblems'], ['watches', 'watches']];
  // 0.1.55 §11: notify + quiet hours live in General › Notifications; looking out and the
  // brief in Background; watches and mutes are managed in the Inbox. Without `only`, all.
  const show = (k: ProactiveBlock) => !only || only.includes(k);
  const content = <div className="space-y-5">
    {error && <p role="alert" className="text-[11px] text-destructive">{error}</p>}
    {show('looking') && <>
        <Toggle id="proactive-toggle-enabled" label={t('proactive.settings.enabled')} desc={t('proactive.settings.enabledDesc')}
          checked={config.enabled} onChange={(v) => void save({ enabled: v })} />
        <fieldset className="space-y-3" disabled={!config.enabled}>
          <legend className="mb-2 text-[12px] text-muted-foreground">{t('proactive.settings.sources')}</legend>
          {sources.map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs">
            <input type="checkbox" data-testid={`proactive-source-${key}`} checked={Boolean(config[key])} onChange={(e) => void save({ [key]: e.target.checked } as Partial<ProactiveConfig>)}
              className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-0" />{t(`proactive.settings.${label}`)}</label>)}
        </fieldset>
    </>}
    {show('notify') && <>
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
    </>}
    {show('brief') && <>
        <Toggle id="proactive-toggle-brief" label={t('proactive.settings.brief')} desc={t('proactive.settings.briefDesc')}
          checked={config.brief_enabled} onChange={(v) => void save({ brief_enabled: v })} />
        {config.brief_enabled && <label className="flex items-center gap-2 text-xs">{t('proactive.settings.briefAt')}
          <input type="time" data-testid="proactive-brief-time" className={field} value={config.brief_time} onChange={(e) => e.target.value && void save({ brief_time: e.target.value })} /></label>}
        <p className="text-[11px] text-muted-foreground max-w-xl">{t('proactive.settings.diagnosisPointer')}</p>
    </>}
    {show('watches') && <WatchesPanel watchesOn={config.enabled && config.watches} />}
  </div>;
  if (bare) return <div data-testid="settings-proactive">{content}</div>;
  return (
    <div className="bg-surface border border-border rounded-2xl p-6" data-testid="settings-proactive">
      <div className="flex items-center gap-2 mb-1">
        <BellRing className="w-3.5 h-3.5 text-subtle-foreground" aria-hidden />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('proactive.settings.title')}</h3>
      </div>
      <p className="text-[11px] text-muted-foreground font-sans max-w-2xl mb-5">{t('proactive.settings.lede')}</p>
      {content}
    </div>
  );
}

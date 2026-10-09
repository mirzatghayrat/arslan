import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Hand } from 'lucide-react';
import { request } from '../../api/client';

/**
 * Arslan Hands (0.1.53) — Mac apps through a helper that alone holds the
 * Accessibility permission. Its own endpoint and settings file, so 0.1.52's
 * settings changes and this one never collide. The never-list shown here is the
 * list the helper enforces (one shared file); the user can only add to it.
 * Hands v2 (spec 2026-10-08-0157 §7.4): Screen Recording, the screenshot /
 * borrow / away switches, apps allowed for good (kept by bundle id, so only a
 * running app can be added) and apps never screenshotted.
 */
export interface HandsState {
  available: boolean;
  enabled: boolean;
  cursor: boolean;
  never: string[];
  built_in: { never: string[]; look_only: string[]; click_only: string[] };
  screenshots: boolean;
  borrow: boolean;
  away: boolean;
  always: { bundle_id: string; name: string; since: string }[];
  no_screenshots: string[];
  running?: boolean;
  accessibility?: boolean;
  screen_recording?: boolean;
}

type Settable = 'enabled' | 'cursor' | 'never' | 'screenshots' | 'borrow' | 'away' | 'no_screenshots';

export const getHands = () => request<HandsState>('/hands');
export const putHands = (body: Partial<Pick<HandsState, Settable>>) =>
  request<HandsState>('/hands', { method: 'PUT', body: JSON.stringify(body) });
export const checkHands = () =>
  request<{ running: boolean; accessibility?: boolean; screen_recording?: boolean }>('/hands/check', { method: 'POST' });
export const askHandsPermission = (kind: 'accessibility' | 'screen' = 'accessibility') =>
  request<{ accessibility?: boolean; screen_recording?: boolean }>('/hands/permission',
    { method: 'POST', body: JSON.stringify({ kind }) });
type AlwaysReply = Partial<HandsState> & { ok: boolean; code?: string };
export const addAlways = (app: string) =>
  request<AlwaysReply>('/hands/always', { method: 'POST', body: JSON.stringify({ app }) });
export const removeAlways = (bundleId: string) =>
  request<AlwaysReply>(`/hands/always/${encodeURIComponent(bundleId)}`, { method: 'DELETE' });

export default function HandsSection() {
  const { t } = useTranslation();
  const [state, setState] = useState<HandsState | null>(null);
  const [draft, setDraft] = useState('');
  const [alwaysDraft, setAlwaysDraft] = useState('');
  const [alwaysError, setAlwaysError] = useState(false);
  const [shotsDraft, setShotsDraft] = useState('');

  useEffect(() => {
    getHands().then(setState).catch(() => setState(null));
  }, []);

  if (!state) return null;
  const save = (body: Parameters<typeof putHands>[0]) =>
    putHands(body).then((next) => setState((s) => ({ ...(s ?? next), ...next })));
  const access = state.accessibility === true ? 'granted' : state.accessibility === false ? 'notGranted' : 'unknown';
  const screen = state.screen_recording === true ? 'screenGranted'
    : state.screen_recording === false ? 'screenNotGranted' : 'unknown';
  const merge = (next: Partial<HandsState>) => setState((p) => p && { ...p, ...next });
  const chips = (testid: string, items: { key: string; label: string }[], remove: (key: string) => void) => (
    <ul className="mt-1 flex flex-wrap gap-2" data-testid={testid}>
      {items.map(({ key, label }) => (
        <li key={key} className="text-[11px] font-sans border border-border rounded-full px-2 py-0.5 flex items-center gap-1">
          {label}
          <button type="button" aria-label={`${t('hands.settings.remove')} ${label}`} onClick={() => remove(key)}>×</button>
        </li>
      ))}
    </ul>
  );
  const adder = (testid: string, value: string, onValue: (v: string) => void, placeholder: string,
    onAdd: (v: string) => void) => (
    <form className="mt-2 flex gap-2" onSubmit={(e) => {
      e.preventDefault();
      if (value.trim()) onAdd(value.trim());
    }}>
      <input value={value} onChange={(e) => onValue(e.target.value)} maxLength={120}
        placeholder={t(placeholder)} data-testid={`${testid}-input`}
        className="text-[11px] font-sans bg-background border border-border rounded-md px-2 py-1 w-56" />
      <button type="submit" className="runcmd-card__btn runcmd-card__btn--ghost" data-testid={`${testid}-add`}>
        {t('hands.settings.add')}</button>
    </form>
  );
  const permission = (label: string, testid: string, text: string, missing: boolean, kind: 'accessibility' | 'screen') => (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h4 className="text-[13px] font-medium text-foreground">{t(label)}</h4>
        <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl" data-testid={testid}>
          {t(`hands.settings.${text}`)}</p>
      </div>
      <div className="flex gap-2 shrink-0">
        {kind === 'accessibility' &&
          <button type="button" className="runcmd-card__btn runcmd-card__btn--ghost" data-testid="hands-check"
            onClick={() => checkHands().then(merge)}>{t('hands.settings.check')}</button>}
        {missing &&
          <button type="button" className="runcmd-card__btn runcmd-card__btn--primary"
            data-testid={kind === 'screen' ? 'hands-ask-screen' : 'hands-ask'}
            onClick={() => askHandsPermission(kind).then(merge)}>{t('hands.settings.ask')}</button>}
      </div>
    </div>
  );
  const toggle = (id: string, label: string, desc: string, checked: boolean, onChange: (v: boolean) => void) => (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h4 className="text-[13px] font-medium text-foreground">{t(label)}</h4>
        <p className="text-[12px] leading-snug text-muted-foreground mt-0.5 max-w-xl">{t(desc)}</p>
      </div>
      <input id={id} data-testid={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="kit-switch mt-0.5" />
    </div>
  );
  const list = (label: string, items: string[]) => (
    <div>
      <h4 className="text-[11px] font-semibold text-foreground font-sans">{t(label)}</h4>
      <p className="text-[11px] text-muted-foreground font-sans mt-0.5">{items.join(' · ')}</p>
    </div>
  );
  return (
    <div className="bg-surface border border-border rounded-2xl p-6" data-testid="settings-hands">
      <div className="flex items-center gap-2 mb-1">
        <Hand className="w-3.5 h-3.5 text-subtle-foreground" aria-hidden />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">
          {t('hands.settings.title')}
        </h3>
      </div>
      <p className="text-[11px] text-muted-foreground font-sans max-w-2xl mb-5">{t('hands.settings.lede')}</p>
      {!state.available
        ? <p className="text-[11px] text-muted-foreground font-sans" data-testid="hands-unavailable">{t('hands.settings.unavailable')}</p>
        : <div className="space-y-5">
          {toggle('hands-enabled-toggle', 'hands.settings.enabled', 'hands.settings.enabledDesc', state.enabled,
            (v) => save({ enabled: v }))}
          <div className="h-[1px] bg-border/40" />
          {toggle('hands-cursor-toggle', 'hands.settings.cursor', 'hands.settings.cursorDesc', state.cursor,
            (v) => save({ cursor: v }))}
          <div className="h-[1px] bg-border/40" />
          {permission('hands.settings.access', 'hands-access', access, state.accessibility === false, 'accessibility')}
          {permission('hands.settings.screen', 'hands-screen', screen, state.screen_recording === false, 'screen')}
          <div className="h-[1px] bg-border/40" />
          {toggle('hands-screenshots-toggle', 'hands.settings.screenshots', 'hands.settings.screenshotsDesc',
            state.screenshots, (v) => save({ screenshots: v }))}
          {toggle('hands-borrow-toggle', 'hands.settings.borrow', 'hands.settings.borrowDesc', state.borrow,
            (v) => save({ borrow: v }))}
          {toggle('hands-away-toggle', 'hands.settings.away', 'hands.settings.awayDesc', state.away,
            (v) => save({ away: v }))}
          <div className="h-[1px] bg-border/40" />
          <div>
            <h4 className="text-[11px] font-semibold text-foreground font-sans">{t('hands.settings.always')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{t('hands.settings.alwaysDesc')}</p>
            {chips('hands-always', state.always.map((a) => ({ key: a.bundle_id, label: a.name || a.bundle_id })),
              (bundleId) => removeAlways(bundleId).then(merge))}
            {adder('hands-always', alwaysDraft, (v) => { setAlwaysDraft(v); setAlwaysError(false); },
              'hands.settings.alwaysPlaceholder', (app) => addAlways(app).then((r) => {
                if (r.ok) { merge(r); setAlwaysDraft(''); } else setAlwaysError(true);
              }))}
            {alwaysError &&
              <p className="text-[11px] text-muted-foreground font-sans mt-1" data-testid="hands-always-error">
                {t('hands.settings.alwaysNotRunning')}</p>}
          </div>
          <div>
            <h4 className="text-[11px] font-semibold text-foreground font-sans">{t('hands.settings.noShots')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5">{t('hands.settings.noShotsDesc')}</p>
            {chips('hands-no-shots', state.no_screenshots.map((n) => ({ key: n, label: n })),
              (name) => save({ no_screenshots: state.no_screenshots.filter((n) => n !== name) }))}
            {adder('hands-no-shots', shotsDraft, setShotsDraft, 'hands.settings.placeholder',
              (name) => save({ no_screenshots: [...state.no_screenshots, name] }).then(() => setShotsDraft('')))}
          </div>
          <div className="h-[1px] bg-border/40" />
          {list('hands.settings.never', state.built_in.never)}
          {list('hands.settings.lookOnly', state.built_in.look_only)}
          {list('hands.settings.clickOnly', state.built_in.click_only)}
          <div>
            <h4 className="text-[11px] font-semibold text-foreground font-sans">{t('hands.settings.mine')}</h4>
            {chips('hands-never-mine', state.never.map((n) => ({ key: n, label: n })),
              (app) => save({ never: state.never.filter((n) => n !== app) }))}
            {adder('hands-never', draft, setDraft, 'hands.settings.placeholder',
              (app) => save({ never: [...state.never, app] }).then(() => setDraft('')))}
          </div>
        </div>}
    </div>
  );
}

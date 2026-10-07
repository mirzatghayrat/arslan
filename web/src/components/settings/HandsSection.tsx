import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Hand } from 'lucide-react';
import { request } from '../../api/client';

/**
 * Arslan Hands (0.1.53) — Mac apps through a helper that alone holds the
 * Accessibility permission. Its own endpoint and settings file, so 0.1.52's
 * settings changes and this one never collide. The never-list shown here is the
 * list the helper enforces (one shared file); the user can only add to it.
 */
export interface HandsState {
  available: boolean;
  enabled: boolean;
  cursor: boolean;
  never: string[];
  built_in: { never: string[]; look_only: string[]; click_only: string[] };
  running?: boolean;
  accessibility?: boolean;
}

export const getHands = () => request<HandsState>('/hands');
export const putHands = (body: Partial<Pick<HandsState, 'enabled' | 'cursor' | 'never'>>) =>
  request<HandsState>('/hands', { method: 'PUT', body: JSON.stringify(body) });
export const checkHands = () => request<{ running: boolean; accessibility?: boolean }>('/hands/check', { method: 'POST' });
export const askHandsPermission = () => request<{ accessibility: boolean }>('/hands/permission', { method: 'POST' });

export default function HandsSection() {
  const { t } = useTranslation();
  const [state, setState] = useState<HandsState | null>(null);
  const [draft, setDraft] = useState('');

  useEffect(() => {
    getHands().then(setState).catch(() => setState(null));
  }, []);

  if (!state) return null;
  const save = (body: Parameters<typeof putHands>[0]) =>
    putHands(body).then((next) => setState((s) => ({ ...(s ?? next), ...next })));
  const access = state.accessibility === true ? 'granted' : state.accessibility === false ? 'notGranted' : 'unknown';
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
          <div className="flex items-start justify-between gap-4">
            <div>
              <h4 className="text-[13px] font-medium text-foreground">{t('hands.settings.access')}</h4>
              <p className="text-[11px] text-muted-foreground font-sans mt-0.5" data-testid="hands-access">
                {t(`hands.settings.${access}`)}</p>
            </div>
            <div className="flex gap-2 shrink-0">
              <button type="button" className="runcmd-card__btn runcmd-card__btn--ghost" data-testid="hands-check"
                onClick={() => checkHands().then((s) => setState((p) => p && { ...p, ...s }))}>{t('hands.settings.check')}</button>
              {state.accessibility === false &&
                <button type="button" className="runcmd-card__btn runcmd-card__btn--primary" data-testid="hands-ask"
                  onClick={() => askHandsPermission().then((s) => setState((p) => p && { ...p, ...s }))}>{t('hands.settings.ask')}</button>}
            </div>
          </div>
          <div className="h-[1px] bg-border/40" />
          {list('hands.settings.never', state.built_in.never)}
          {list('hands.settings.lookOnly', state.built_in.look_only)}
          {list('hands.settings.clickOnly', state.built_in.click_only)}
          <div>
            <h4 className="text-[11px] font-semibold text-foreground font-sans">{t('hands.settings.mine')}</h4>
            <ul className="mt-1 flex flex-wrap gap-2" data-testid="hands-never-mine">
              {state.never.map((app) => (
                <li key={app} className="text-[11px] font-sans border border-border rounded-full px-2 py-0.5 flex items-center gap-1">
                  {app}
                  <button type="button" aria-label={`${t('hands.settings.remove')} ${app}`}
                    onClick={() => save({ never: state.never.filter((n) => n !== app) })}>×</button>
                </li>
              ))}
            </ul>
            <form className="mt-2 flex gap-2" onSubmit={(e) => {
              e.preventDefault();
              if (draft.trim()) save({ never: [...state.never, draft.trim()] }).then(() => setDraft(''));
            }}>
              <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={120}
                placeholder={t('hands.settings.placeholder')} data-testid="hands-never-input"
                className="text-[11px] font-sans bg-background border border-border rounded-md px-2 py-1 w-56" />
              <button type="submit" className="runcmd-card__btn runcmd-card__btn--ghost" data-testid="hands-never-add">
                {t('hands.settings.add')}</button>
            </form>
          </div>
        </div>}
    </div>
  );
}

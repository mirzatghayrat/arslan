import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import { ICON_STYLES, useIconStore } from '../../stores/iconStore';
import { shellAvailable } from '../../lib/shell';

export default function IconPicker() {
  const { t } = useTranslation();
  const { style, select, pending, error } = useIconStore();
  return <section className="space-y-3 border-t border-border pt-5">
    <div>
      <h4 id="app-icon-label" className="text-sm font-medium text-foreground">{t('settings.appIcon')}</h4>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t(shellAvailable() ? 'settings.appIconDesktopHint' : 'settings.appIconBrowserHint')}</p>
    </div>
    <div role="radiogroup" aria-labelledby="app-icon-label" aria-busy={pending} className="grid grid-cols-2 gap-3 max-w-md">
      {ICON_STYLES.map(option => <label key={option} className={`relative flex min-w-0 cursor-pointer flex-col items-center gap-2 rounded-xl border p-3 transition-colors focus-within:ring-2 focus-within:ring-ring ${style === option ? 'border-primary bg-primary/5' : 'border-border hover:bg-surface-raised'} ${pending ? 'opacity-60' : ''}`}>
        <input type="radio" name="app-icon" value={option} checked={style === option} disabled={pending}
          onChange={() => void select(option)} className="sr-only" />
        <img src={`/brand/${option}.png?v=20260923`} alt="" draggable={false} className="h-20 w-20 object-contain" />
        <span className="text-center text-xs font-medium leading-relaxed">{t(`settings.appIcon_${option}`)}</span>
        {style === option && <Check aria-hidden className="absolute right-2 top-2 h-4 w-4 text-primary" />}
      </label>)}
    </div>
    {error && <p role="alert" className="text-xs leading-relaxed text-danger">{t('settings.appIconError')}</p>}
  </section>;
}

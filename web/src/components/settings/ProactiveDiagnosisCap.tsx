import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { proactiveApi } from '../../api/proactive';
import { proactiveErrorText } from '../../lib/proactive';

/** Daily limits offered, in US$. 0 = off. A stored value outside this list (set through the
 * API) is shown as itself rather than silently replaced. */
export const DIAGNOSIS_LIMITS = [0, 0.25, 0.5, 1, 2, 5];

/**
 * The one proactivity control that spends money, so it lives in Automation beside the other
 * spenders and their warnings (the contract in sectionRegistry). Everything else about
 * proactivity is free and lives in its own section.
 */
export default function ProactiveDiagnosisCap() {
  const { t } = useTranslation();
  const [limit, setLimit] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    proactiveApi.config().then((config) => { if (alive) setLimit(config.diagnosis_daily_usd); })
      .catch((cause) => { if (alive) setError(proactiveErrorText(t, 'settings', cause)); });
    return () => { alive = false; };
  }, [t]);
  async function choose(value: number) {
    const before = limit;
    setLimit(value); setError(null);
    try { setLimit((await proactiveApi.saveConfig({ diagnosis_daily_usd: value })).diagnosis_daily_usd); }
    catch (cause) { setLimit(before); setError(proactiveErrorText(t, 'settings', cause)); }
  }
  const options = limit !== null && !DIAGNOSIS_LIMITS.includes(limit) ? [...DIAGNOSIS_LIMITS, limit].sort((a, b) => a - b) : DIAGNOSIS_LIMITS;
  return (
    <div className="flex items-start justify-between gap-4" data-testid="settings-proactive-diagnosis">
      <div>
        <h4 className="text-xs font-bold text-foreground font-sans">{t('proactive.settings.diagnosisTitle')}</h4>
        <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{t('proactive.settings.diagnosisDesc')}</p>
        <p className="mt-1 flex items-start gap-1.5 text-[11px] text-warning font-sans max-w-xl" data-testid="proactive-diagnosis-spend-note">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-[1px]" aria-hidden />
          <span>{t('proactive.settings.diagnosisHonest')}</span>
        </p>
        {error && <p role="alert" className="mt-1 text-[11px] text-destructive">{error}</p>}
      </div>
      <label className="flex shrink-0 flex-col items-end gap-1 text-[11px] text-muted-foreground">
        {t('proactive.settings.diagnosisLimit')}
        <select data-testid="proactive-diagnosis-limit" disabled={limit === null} value={limit ?? 0} onChange={(e) => void choose(Number(e.target.value))}
          className="rounded-lg border border-border bg-background px-2 py-1 text-xs text-foreground">
          {options.map((value) => <option key={value} value={value}>{value === 0 ? t('proactive.settings.diagnosisOff') : `$${value.toFixed(2)}`}</option>)}
        </select>
      </label>
    </div>
  );
}

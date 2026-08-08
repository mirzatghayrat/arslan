/**
 * Says WHY stored secrets cannot be read, in the user's language, per verdict.
 *
 * Renders nothing when the install is healthy, and nothing while the diagnosis has
 * not arrived yet — guessing during load would put a data-loss warning on every cold
 * start of a perfectly fine install, and a warning that cries wolf is worse than none.
 *
 * role="status", not "alert": this describes a standing property of the install, not
 * an event, and an alert would interrupt a screen reader on every settings render.
 */
import { useTranslation } from 'react-i18next';

import { VERDICT_COPY_KEY, cryptoNoticeTone, needsCryptoNotice, type CryptoHealth } from '../../lib/cryptoHealth';

export default function CryptoHealthNotice({ health }: { health: CryptoHealth | null }) {
  const { t } = useTranslation();
  if (!needsCryptoNotice(health) || !health) return null;

  const tone = cryptoNoticeTone(health.verdict);
  const border = tone === 'danger' ? 'border-danger/40 bg-danger/10' : 'border-warning/40 bg-warning/10';
  const text = tone === 'danger' ? 'text-danger' : 'text-warning';

  return (
    <div
      role="status"
      data-testid="crypto-health-notice"
      data-verdict={health.verdict}
      className={`rounded-xl border ${border} px-3 py-2.5 space-y-1`}
    >
      <p className={`text-[10.5px] font-mono font-semibold uppercase tracking-wide ${text}`}>
        {t('settings.cryptoHealthTitle')}
      </p>
      <p className={`text-[11px] font-sans leading-relaxed ${text}`}>
        {t(`settings.${VERDICT_COPY_KEY[health.verdict]}`)}
      </p>
      {/* The count, so "some of your keys" is a number rather than a feeling. */}
      <p className="text-[10px] font-mono text-subtle-foreground">
        {t('settings.cryptoHealthCount')}: {health.undecryptable}
        {health.recoverable > 0 ? ` · ${t('settings.cryptoHealthRecoverableCount')}: ${health.recoverable}` : ''}
      </p>
    </div>
  );
}

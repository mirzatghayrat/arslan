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

import { Notice } from '../kit';
import { VERDICT_COPY_KEY, cryptoNoticeTone, needsCryptoNotice, type CryptoHealth } from '../../lib/cryptoHealth';

export default function CryptoHealthNotice({ health }: { health: CryptoHealth | null }) {
  const { t } = useTranslation();
  if (!needsCryptoNotice(health) || !health) return null;

  const tone = cryptoNoticeTone(health.verdict);
  // 0.1.55: the kit's Notice; still role="status" (a standing property, see above).
  return (
    <Notice tone={tone === 'danger' ? 'error' : 'warn'} role="status" testId="crypto-health-notice"
      attrs={{ 'data-verdict': health.verdict }} title={t('settings.cryptoHealthTitle')}>
      {t(`settings.${VERDICT_COPY_KEY[health.verdict]}`)}
      {/* The count, so "some of your keys" is a number rather than a feeling. */}
      <span className="mt-1 block font-mono text-[11px] text-subtle-foreground">
        {t('settings.cryptoHealthCount')}: {health.undecryptable}
        {health.recoverable > 0 ? ` · ${t('settings.cryptoHealthRecoverableCount')}: ${health.recoverable}` : ''}
      </span>
    </Notice>
  );
}

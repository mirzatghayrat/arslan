import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { identitySummary, readAppIdentity, type AppIdentity } from '../../lib/appIdentity';

export default function AppIdentityCard() {
  const { t } = useTranslation();
  const [identity, setIdentity] = useState<AppIdentity | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'copyFailed'>('idle');
  useEffect(() => {
    let disposed = false;
    void readAppIdentity().then(value => { if (!disposed) setIdentity(value); });
    return () => { disposed = true; };
  }, []);

  async function copy() {
    if (!identity) return;
    try {
      await navigator.clipboard.writeText(identitySummary(identity));
      setCopyState('copied');
    } catch {
      setCopyState('copyFailed');
    }
  }

  return (
    <section data-testid="app-identity" aria-label={t('appIdentity.title')}
      className="mb-4 rounded-lg border border-border px-3 py-2 text-xs break-words">
      <div className="font-medium">{t('appIdentity.title')}</div>
      <p className="mt-1 text-muted-foreground" aria-live="polite">
        {!identity ? t('appIdentity.loading') : identity.client === 'browser'
          ? t('appIdentity.browser') : identity.version
            ? `${identity.version} · ${t(`appIdentity.${identity.channel}`)}`
            : t('appIdentity.unknown')}
      </p>
      {identity?.channel === 'preview' && (
        <p className="mt-2 text-muted-foreground">{t('appIdentity.previewHint')}</p>
      )}
      {identity && <details className="mt-2">
        <summary className="cursor-pointer text-muted-foreground">{t('appIdentity.summary')}</summary>
        <p className="mt-2 text-muted-foreground">{t('appIdentity.privacy')}</p>
        <pre className="mt-2 whitespace-pre-wrap break-all text-[10px]">{identitySummary(identity)}</pre>
        <button type="button" onClick={() => void copy()}
          className="mt-2 rounded border border-border px-2 py-1 hover:bg-surface focus-visible:ring-2 focus-visible:ring-primary">
          {t('appIdentity.copy')}
        </button>
        <p role="status">{copyState !== 'idle' ? t(`appIdentity.${copyState}`) : ''}</p>
      </details>}
    </section>
  );
}

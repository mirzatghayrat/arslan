import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDownCircle, X } from 'lucide-react';
import { fetchUpdateStatus, requestInstall, updaterAvailable, type UpdateStatus } from '../lib/updater';

/** Corner update prompt (v0.1.5 UX, user-decided): never a blocking dialog,
 * never a silent download. Appears bottom-right when the shell's startup or
 * menu-triggered check staged an update; nothing downloads until Install is
 * clicked, and the shell restarts itself after a successful install. "Later"
 * hides the pill for this run (sessionStorage — a fresh launch re-offers).
 * Renders nothing in a plain browser (no Tauri IPC). */
export default function UpdatePill() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [dismissed, setDismissed] = useState<string>(
    () => sessionStorage.getItem('arslan-update-dismissed') ?? '',
  );

  useEffect(() => {
    if (!updaterAvailable()) return;
    let alive = true;
    const poll = async () => {
      const s = await fetchUpdateStatus();
      if (alive && s) setStatus(s);
    };
    poll();
    const id = setInterval(poll, 60_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!status || status.state === 'none') return null;
  if (status.state === 'available' && dismissed === status.version) return null;

  const installing = status.state === 'downloading';
  const failed = status.state === 'error';

  return (
    <div
      data-testid="update-pill"
      className="fixed bottom-4 right-4 z-[90] flex items-center gap-3 rounded-xl border border-border bg-surface-raised/95 px-4 py-3 shadow-lg backdrop-blur text-xs"
    >
      <ArrowDownCircle className={`w-4 h-4 flex-shrink-0 ${installing ? 'animate-pulse text-primary' : failed ? 'text-danger' : 'text-primary'}`} />
      <div className="flex flex-col gap-0.5 min-w-0">
        <span className="font-medium text-foreground">
          {failed
            ? t('updater.failed')
            : installing
              ? t('updater.installing', { version: status.version })
              : t('updater.available', { version: status.version })}
        </span>
        {failed && status.error && (
          <span className="text-[10.5px] text-subtle-foreground truncate max-w-[260px]" title={status.error}>
            {status.error}
          </span>
        )}
        {!failed && !installing && (
          <span className="text-[10.5px] text-subtle-foreground">{t('updater.restart_note')}</span>
        )}
      </div>
      {!installing && !failed && (
        <button
          type="button"
          onClick={() => { void requestInstall(); setStatus({ ...status, state: 'downloading' }); }}
          className="rounded-lg bg-primary px-3 py-1.5 font-medium text-primary-foreground hover:opacity-90 transition-opacity"
        >
          {t('updater.install')}
        </button>
      )}
      {!installing && (
        <button
          type="button"
          aria-label={t('updater.later')}
          title={t('updater.later')}
          onClick={() => {
            sessionStorage.setItem('arslan-update-dismissed', status.version);
            setDismissed(status.version);
            if (failed) setStatus(null);
          }}
          className="text-subtle-foreground hover:text-foreground transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

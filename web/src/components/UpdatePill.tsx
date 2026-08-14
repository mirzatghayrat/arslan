import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDownCircle, X } from 'lucide-react';
import { fetchUpdateStatus, requestInstall, subscribeUpdateStatus, updaterAvailable, type UpdateStatus } from '../lib/updater';

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
    // The push path. A check lasts 1-3s against a 60s poll, so the "checking"
    // state only exists on screen because the shell announces it.
    const unsubscribe = subscribeUpdateStatus((s) => { if (alive) setStatus(s); });
    return () => { alive = false; clearInterval(id); unsubscribe(); };
  }, []);

  // Allow-list, not deny-list: an unknown/empty state (e.g. a newer shell
  // vocabulary, or the pre-check default) must render NOTHING, not a blank pill.
  if (!status || !['checking', 'available', 'downloading', 'error'].includes(status.state)) return null;
  if (status.state === 'available' && dismissed === status.version) return null;

  const installing = status.state === 'downloading';
  const failed = status.state === 'error';

  // Transient, not a todo: nothing to click, nothing to dismiss. It removes
  // itself when the shell reports the check's outcome.
  if (status.state === 'checking') {
    return (
      <div
        data-testid="update-pill"
        className="fixed bottom-4 right-4 z-[90] flex items-center gap-3 rounded-xl border border-border bg-surface-raised/95 px-4 py-3 shadow-lg backdrop-blur text-xs"
      >
        <CheckingMatrix />
        <span className="font-medium text-foreground">{t('updater.checking')}</span>
      </div>
    );
  }

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

/** 7-row triangle dot matrix with a row sweep — the visual the user picked
 * (sv-matrix triangle-5), rebuilt in plain CSS: the reference is Svelte and a
 * dependency for 28 dots would be absurd. The sweep stops under
 * prefers-reduced-motion (a vestibular trigger, not a taste setting) and the
 * static matrix remains as the indicator. */
function CheckingMatrix() {
  const rows = Array.from({ length: 7 }, (_, r) => r);
  return (
    <span data-testid="checking-matrix" className="arslan-checking-matrix" aria-hidden>
      <style>{`
        .arslan-checking-matrix { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; }
        .arslan-checking-matrix .m-row { display: flex; gap: 2px; }
        .arslan-checking-matrix .m-dot {
          width: 3px; height: 3px; border-radius: 50%;
          background: currentColor; color: var(--color-primary, #d97706);
          opacity: .25;
          animation: arslan-row-sweep 1.4s ease-in-out infinite;
        }
        @keyframes arslan-row-sweep {
          0%, 100% { opacity: .25; }
          18%      { opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          .arslan-checking-matrix .m-dot { animation: none; opacity: .6; }
        }
      `}</style>
      {rows.map((r) => (
        <span key={r} className="m-row">
          {Array.from({ length: r + 1 }, (_, c) => (
            <span key={c} className="m-dot" style={{ animationDelay: `${r * 0.12}s` }} />
          ))}
        </span>
      ))}
    </span>
  );
}

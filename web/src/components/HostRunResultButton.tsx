import { useState } from 'react';
import { MoreHorizontal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useDismissable } from '../hooks/useDismissable';

/** A durable result entry for a run (host or expert). 0.1.42: diagnostics, so it
 *  sits behind the answer's "⋯" menu instead of a button under every reply. */
export default function HostRunResultButton({ runId, onOpen }: {
  runId?: number | null;
  onOpen: (runId: number) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, () => setOpen(false));
  if (!Number.isSafeInteger(runId) || (runId ?? 0) <= 0) return null;
  return <span className="relative mt-1 inline-block">
    <button ref={anchorRef} type="button" aria-label={t('ui.moreActions')} aria-haspopup="menu" aria-expanded={open}
      onClick={() => setOpen(value => !value)}
      className="rounded p-1 text-subtle-foreground hover:bg-foreground/5 hover:text-foreground">
      <MoreHorizontal size={14} aria-hidden />
    </button>
    {open && <div ref={floatingRef} role="menu"
      className="absolute left-0 z-20 mt-1 min-w-36 rounded-md border border-border bg-background p-1 shadow-md">
      <button type="button" role="menuitem" className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-primary/5"
        onClick={() => { setOpen(false); onOpen(runId!); }}>{t('replay.view_replay')}</button>
    </div>}
  </span>;
}

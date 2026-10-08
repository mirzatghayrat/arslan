import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { useAnswerKeys, useLayer } from "./layers";

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The one dialog (0.1.55): one portal, one stacking level, role=dialog +
 * aria-modal, focus kept inside, Esc closes, a real close button. Replaces seven
 * modal implementations (z-index 20…150, one without role=dialog).
 */
export function Dialog({ open, onClose, title, children, footer, width = 520, testId = "kit-dialog", bare = false, onSubmit,
  closeLabel, busy = false, padded = false }: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
  testId?: string;
  /** No header row (ConfirmSheet). */
  bare?: boolean;
  /** ⌘⏎ submits (ConfirmSheet, forms). Esc always closes. */
  onSubmit?: () => void;
  closeLabel?: string;
  /** While busy, Esc / the scrim / the close button do nothing. */
  busy?: boolean;
  /** Pad the body (forms written for the old CompanionDialog). */
  padded?: boolean;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const top = useLayer(open);
  const close = () => { if (!busy) onClose(); };
  useAnswerKeys(open && top, { onDecline: close, onAllow: onSubmit });

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel.current)?.focus();
    return () => before?.focus?.();
  }, [open]);

  if (!open) return null;
  const trap = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab" || !panel.current) return;
    const all = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (!all.length) return;
    const [first, last] = [all[0], all[all.length - 1]];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  return createPortal(
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4" data-testid={`${testId}-layer`}>
      <div className="absolute inset-0 bg-scrim" onClick={close} aria-hidden="true" />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={title ? titleId : undefined}
        tabIndex={-1} onKeyDown={trap} data-testid={testId}
        className="relative flex max-h-[85vh] w-full flex-col overflow-hidden rounded-2xl border border-border bg-surface text-foreground shadow-kit"
        style={{ maxWidth: width }}>
        {!bare && (
          <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
            <h2 id={titleId} className="text-[16px] font-bold">{title}</h2>
            <button type="button" aria-label={closeLabel ?? t("kit.close")} onClick={close} disabled={busy}
              className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-fill text-muted-foreground hover:text-foreground">
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        )}
        <div className={`min-h-0 overflow-auto ${padded ? "p-5" : ""}`}>{bare && title ? <h2 id={titleId} className="sr-only">{title}</h2> : null}{children}</div>
        {footer ? <div className="flex justify-end gap-2.5 px-5 pb-4 pt-3">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

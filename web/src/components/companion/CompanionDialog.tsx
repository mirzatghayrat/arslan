import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

export const inputClass = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40";
export const buttonClass = "inline-flex items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-foreground/5 disabled:opacity-50 disabled:cursor-not-allowed";
export const primaryClass = `${buttonClass} bg-primary text-primary-foreground hover:bg-primary/90`;

export default function CompanionDialog({ title, children, onClose, busy = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("textarea,input,select,button")?.focus();
    return () => { previous?.focus(); };
  }, []);
  return createPortal(<div className="fixed inset-0 z-[150] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm">
    <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId}
      className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-border bg-background p-5 text-foreground shadow-2xl"
      onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); if (!busy) onClose(); }
        if (event.key === "Tab") {
          const elements = Array.from(ref.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex="0"]') ?? []);
          const first = elements[0], last = elements[elements.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }
      }}>
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
        <button type="button" className={buttonClass} disabled={busy} onClick={onClose} aria-label={t("companion.close")}><X size={16} /></button>
      </div>
      {children}
    </div>
  </div>, document.body);
}

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Dialog } from "../kit";

// 0.1.55: the shared form controls take the kit's look — label-colour primary (the palette's
// orange stays a brand accent), a neutral fill for secondary, no uppercase.
export const inputClass = "w-full rounded-[10px] border border-border bg-surface-raised px-3 py-2 text-sm text-foreground placeholder:text-subtle-foreground focus:outline-none focus:ring-2 focus:ring-foreground/20";
export const buttonClass = "inline-flex items-center justify-center gap-2 rounded-[10px] bg-fill px-3 py-2 text-[13px] font-semibold text-foreground hover:bg-fill-strong disabled:opacity-50 disabled:cursor-not-allowed";
export const primaryClass = "inline-flex items-center justify-center gap-2 rounded-[10px] bg-foreground px-3 py-2 text-[13px] font-semibold text-background hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed";

/** The companion pages' dialog — since 0.1.55 the kit's one Dialog (one portal, one
 *  stacking level, aria-modal, focus kept inside, Esc), with the same API as before. */
export default function CompanionDialog({ title, children, onClose, busy = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open title={title} onClose={onClose} busy={busy} padded width={576} testId="companion-dialog"
      closeLabel={t("companion.close")}>
      {children}
    </Dialog>
  );
}

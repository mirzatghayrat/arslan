import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * "You have unsaved changes" — shown when Escape is pressed in a DIRTY editor.
 *
 * Ruling ①A. Escape closes a clean editor immediately and asks first in a dirty
 * one. The two alternatives were rejected for reasons worth keeping: closing
 * unconditionally destroys work on a keystroke people press reflexively, and
 * refusing to close at all makes Escape a dead key in exactly the place a user
 * most wants an exit — inconsistent with every other overlay in the app.
 *
 * Inline rather than `window.confirm`: a native dialog steals focus, cannot be
 * styled or translated, and in a Tauri webview looks like the OS is reporting
 * an error.
 */
export default function DiscardChangesBar({
  onDiscard,
  onCancel,
}: {
  onDiscard: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      data-testid="discard-changes"
      role="alertdialog"
      aria-label={t("common.discard_title")}
      className="flex items-center gap-2 px-3 py-2 border-t border-danger/30 bg-danger/10"
    >
      <AlertTriangle className="w-3.5 h-3.5 text-danger shrink-0" />
      <p className="flex-1 text-[11px] font-sans text-muted-foreground">
        {t("common.discard_body")}
      </p>
      <button
        type="button"
        onClick={onCancel}
        className="px-2.5 py-1 rounded-md text-[10.5px] font-sans font-medium text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] transition-all"
      >
        {t("common.keep_editing")}
      </button>
      <button
        type="button"
        data-testid="discard-confirm"
        onClick={onDiscard}
        className="px-2.5 py-1 rounded-md text-[10.5px] font-sans font-bold text-danger bg-danger/10 border border-danger/30 hover:bg-danger/20 transition-all"
      >
        {t("common.discard_ok")}
      </button>
    </div>
  );
}

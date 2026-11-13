import { useTranslation } from "react-i18next";
import { modeInfo, REASON } from "./modes";
import type { PermissionModeControl } from "./usePermissionMode";

/**
 * S5a: above the thread composer. In Plan, the Start button and what it starts in (the mode before plan, else the
 * default); while "Ask only when risky" falls back, why. Otherwise nothing. Start sits here, not in a plan block in
 * the conversation as the demo had it: S5a has no plan message to hang it on.
 */
export default function ModeStrip({ pm }: { pm: PermissionModeControl }) {
  const { t } = useTranslation();
  const { state, defaultMode } = pm;
  if (!state) return null;
  if (state.chosen === "plan") {
    return (
      <div className="max-w-4xl mx-auto mb-2 flex items-center gap-3 text-[12px] text-muted-foreground">
        <button type="button" onClick={() => void pm.start()} data-testid="mode-start"
          className="min-h-[44px] rounded-lg bg-primary px-4 font-medium text-primary-foreground hover:bg-primary-hover">
          {t("modes.start")}</button>
        <span data-testid="mode-starts-in">{t("modes.startsIn", { mode: t(modeInfo(state.previous ?? defaultMode).name) })}</span>
      </div>
    );
  }
  if (!state.fallback) return null;
  return (
    <div role="status" data-testid="mode-fallback"
      className="max-w-4xl mx-auto mb-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[13px] text-foreground">
      {t("modes.fallbackBanner", { reason: t(REASON[state.fallback]) })}
    </div>
  );
}

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { useDismissable } from "../../hooks/useDismissable";
import { useMenuKeyboard } from "../../hooks/useMenuKeyboard";
import { MODES, modeInfo } from "./modes";
import type { PermissionModeControl } from "./usePermissionMode";

/**
 * S5a: the conversation's permission mode, by the composer (both composers). The menu picks one of the four for this
 * conversation from its next step; the label is what applies, "(for now)" while "Ask only when risky" falls back.
 * Until the server answers it shows the default, dimmed, never the last conversation's mode.
 */
export default function PermissionModePill({ pm }: { pm: PermissionModeControl }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, () => setOpen(false));
  const onMenuKey = useMenuKeyboard(open, anchorRef, floatingRef);
  const { state, defaultMode, saveFailed } = pm;
  const chosen = state?.chosen ?? defaultMode;
  const fallback = state?.fallback ?? "";
  const label = fallback ? t("modes.askForNow") : t(modeInfo(chosen).name);
  const dot = modeInfo(fallback ? "ask" : chosen).dot;
  // A sub-session never runs wider than the one that started it (Q4).
  const narrowed = state?.own != null && state.own !== state.chosen;
  const pillClass = `flex min-h-[44px] items-center gap-1.5 rounded-full border border-border bg-background/40 px-2.5 text-[11px] text-muted-foreground${state ? "" : " opacity-60"}`;

  // SIDE-1 (user decision): a side chat only inherits its parent's mode, so it shows it with no menu to change it.
  if (pm.inherited) {
    return (
      <span className="relative flex items-center gap-1.5">
        <span role="img" aria-label={t("modes.pillAria", { label })} title={t("modes.inherited")}
          data-testid="permission-mode-pill" className={pillClass}>
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />
          <span className="truncate" aria-hidden>{label}</span>
        </span>
        <span data-testid="permission-mode-inherited" className="sr-only">{t("modes.inherited")}</span>
      </span>
    );
  }

  return (
    <span className="relative flex items-center gap-1.5">
      <button ref={anchorRef} type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}
        aria-label={t("modes.pillAria", { label })} data-testid="permission-mode-pill"
        className={`${pillClass} hover:border-primary/40`}>
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />
        <span className="truncate">{label}</span><ChevronDown className="h-2.5 w-2.5 shrink-0 opacity-60" />
      </button>
      {saveFailed && <span role="alert" className="text-[10px] text-danger">{t("modes.saveFailed")}</span>}
      {open && <div ref={floatingRef} role="menu" onKeyDown={onMenuKey}
        className="absolute bottom-full left-0 z-50 mb-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-background p-1.5 shadow-lg">
        {MODES.map((m) => (
          <button key={m.mode} type="button" role="menuitemradio" aria-checked={m.mode === chosen}
            onClick={() => { setOpen(false); if (m.mode !== chosen) void pm.pick(m.mode); }}
            className="grid min-h-[44px] w-full grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 rounded-lg px-2 py-2 text-left hover:bg-fill focus:bg-fill focus:outline-none">
            <span className={`mt-1.5 h-1.5 w-1.5 rounded-full ${m.dot}`} aria-hidden />
            <span>
              <span className="block text-[12.5px] font-medium text-foreground">{t(m.name)}</span>
              <span className="block text-[11.5px] leading-snug text-muted-foreground">{t(m.line)}</span>
            </span>
            {m.mode === chosen && <span className="text-[10.5px] text-subtle-foreground">{t("modes.current")}</span>}
          </button>
        ))}
        <div className="mt-1 border-t border-border px-2 pb-1 pt-2 text-[11px] text-subtle-foreground">
          {narrowed && <div data-testid="permission-mode-narrowed">{t("modes.narrowed")}</div>}
          {t("modes.footnote")}
        </div>
      </div>}
    </span>
  );
}

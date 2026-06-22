import { useTranslation } from "react-i18next";
import { useThemeStore } from "../stores/themeStore";
import { PALETTES } from "../theme/palettes";

export function AppearanceSettings() {
  const { t } = useTranslation();
  const { palette, mode, setPalette, toggleMode } = useThemeStore();
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
          {t("settings.palette")}
        </label>
        <div role="radiogroup" className="grid grid-cols-3 gap-2">
          {PALETTES.map((p) => (
            <button
              key={p.id}
              role="radio"
              aria-checked={palette === p.id}
              aria-label={t(p.nameKey)}
              onClick={() => setPalette(p.id)}
              className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs transition-all ${
                palette === p.id ? "border-primary ring-1 ring-ring" : "border-border hover:border-border-strong"
              }`}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-md border border-border" style={{ background: mode === "light" ? p.swatch.bgLight : p.swatch.bg }}>
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.swatch.accent }} />
              </span>
              <span className="text-foreground">{t(p.nameKey)}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-foreground">{t("settings.mode")}</span>
        <button
          onClick={toggleMode}
          aria-label={t("settings.mode")}
          className="rounded-lg border border-border-strong px-3 py-1.5 text-xs text-foreground hover:bg-surface-raised"
        >
          {mode === "dark" ? t("settings.modeDark") : t("settings.modeLight")}
        </button>
      </div>
    </div>
  );
}

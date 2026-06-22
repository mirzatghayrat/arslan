/**
 * NoModelHint — shown in the orchestrator chat area when no LLM provider
 * config exists yet. Non-blocking: disappears as soon as hasModel is true.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { Settings2, AlertTriangle } from "lucide-react";

interface NoModelHintProps {
  /** True when at least one ProviderConfig exists. */
  hasModel: boolean;
  /** Called when the user clicks "Open Settings". */
  onOpenSettings: () => void;
}

export default function NoModelHint({ hasModel, onOpenSettings }: NoModelHintProps) {
  const { t } = useTranslation();

  if (hasModel) return null;

  return (
    <div className="mx-auto mt-4 max-w-xl w-full px-4">
      <div className="flex items-start gap-3 px-4 py-3 rounded-xl border border-warning/40 bg-warning/10 text-warning">
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[12px] font-sans leading-snug text-warning">
            {t("orchestrator.no_model_hint")}
          </p>
        </div>
        <button
          type="button"
          onClick={onOpenSettings}
          className="flex items-center gap-1.5 shrink-0 px-3 py-1.5 rounded-lg border border-warning/50 bg-warning/10 hover:bg-warning/20 text-warning text-[11px] font-mono font-bold uppercase tracking-wider transition-all"
        >
          <Settings2 className="w-3.5 h-3.5" />
          <span>{t("orchestrator.open_settings")}</span>
        </button>
      </div>
    </div>
  );
}

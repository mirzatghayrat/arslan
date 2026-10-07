/**
 * NoModelHint — shown in the orchestrator chat area when no LLM provider
 * config exists yet. Non-blocking: disappears as soon as hasModel is true.
 * 0.1.55: the kit's Notice (warn tone, one sentence, one action).
 */
import { useTranslation } from "react-i18next";
import { Settings2 } from "lucide-react";
import { Button, Notice } from "./kit";

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
    <div className="mx-auto mt-4 w-full max-w-xl px-4">
      <Notice tone="warn" testId="no-model-hint"
        action={<Button size="sm" tone="secondary" onClick={onOpenSettings}><Settings2 className="h-3.5 w-3.5" />{t("orchestrator.open_settings")}</Button>}>
        {t("orchestrator.no_model_hint")}
      </Notice>
    </div>
  );
}

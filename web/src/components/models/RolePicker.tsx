import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import type { ProviderConfig } from "../../api/client.types";
import { useDismissable } from "../../hooks/useDismissable";
import ModelPicker, { type ModelChoice, type ModelNeed } from "./ModelPicker";

/**
 * One row's model in 模型分工 (0.1.58 §6): a button naming the model, opening the same picker as
 * the composer — any model of any provider. `unsetLabel` (when given) offers "不单独设".
 */
export default function RolePicker({ id, configs, current, need, onPick, onUnset, unsetLabel }: {
  id: string; configs: ProviderConfig[]; current: ModelChoice | null; need: ModelNeed;
  onPick: (c: ModelChoice) => void; onUnset?: () => void; unsetLabel?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, () => setOpen(false));
  const label = (c: ProviderConfig) => (c.label?.trim() ? c.label : c.provider);
  const cfg = current ? configs.find((c) => c.id === current.configId) : undefined;
  return (
    <span className="relative inline-block">
      <button ref={anchorRef} type="button" id={id} data-testid={id} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex max-w-sm items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-left text-[12px] hover:border-primary/40">
        <span className="truncate">{cfg && current ? `${label(cfg)} · ${current.model}` : unsetLabel ?? t("models.pick")}</span>
        <ChevronDown size={12} className="shrink-0 opacity-60" />
      </button>
      {open && <div ref={floatingRef} role="dialog" className="absolute left-0 top-full z-50 mt-1 rounded-xl border border-border bg-background p-2 shadow-lg">
        {onUnset && <button type="button" onClick={() => { setOpen(false); onUnset(); }} data-testid={`${id}-unset`}
          className="mb-1 block w-full rounded-lg px-2 py-1.5 text-left text-[12px] text-muted-foreground hover:bg-foreground/[0.04]">{unsetLabel}</button>}
        <ModelPicker configs={configs} current={current} need={need} label={label}
          onPick={(c) => { setOpen(false); onPick(c); }} />
      </div>}
    </span>
  );
}

import { useTranslation } from "react-i18next";
import { Pencil, Check, X, Plus, Minus } from "lucide-react";
import type { SpawnUpdateChanges, SpawnUpdateCurrent } from "../api/client.types";

/**
 * SuggestUpdateCard — Arslan proposes edits to an EXISTING spawn (P2 conversational
 * spawn editing). Renders before→after for persona fields and +/- chips for equipment.
 * Nothing is applied until Confirm sends `confirm_update`; Dismiss just clears the card.
 */
interface Props {
  spawnName: string;
  current: SpawnUpdateCurrent;
  changes: SpawnUpdateChanges;
  reason?: string;
  onConfirm: () => void;
  onDismiss: () => void;
}

function DiffRow({ label, before, after }: { label: string; before: string; after: string }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[9.5px] font-mono uppercase tracking-widest text-subtle-foreground">{label}</div>
      <div className="text-[11px] text-subtle-foreground line-through decoration-danger/50">{before || "—"}</div>
      <div className="text-[11.5px] text-foreground">{after}</div>
    </div>
  );
}

export default function SuggestUpdateCard({ spawnName, current, changes, reason, onConfirm, onDismiss }: Props) {
  const { t } = useTranslation();
  const equipmentDelta: { key: string; add: boolean }[] = [
    ...(changes.add_toolsets ?? []).map((k) => ({ key: k, add: true })),
    ...(changes.add_skills ?? []).map((k) => ({ key: k, add: true })),
    ...(changes.remove_toolsets ?? []).map((k) => ({ key: k, add: false })),
    ...(changes.remove_skills ?? []).map((k) => ({ key: k, add: false })),
  ];

  return (
    <div className="bg-surface border border-primary/30 rounded-2xl p-5 shadow-xl shadow-primary/5 space-y-4 max-w-xl">
      <div className="flex items-center gap-2">
        <Pencil className="w-4 h-4 text-primary shrink-0" />
        <h4 className="text-xs font-bold text-foreground font-sans flex-1">
          {t("orchestrator.update_title", { name: spawnName })}
        </h4>
        <button type="button" onClick={onDismiss} title={t("orchestrator.update_dismiss")}
          className="text-subtle-foreground hover:text-foreground transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      {reason && <p className="text-[11px] text-muted-foreground font-sans leading-relaxed">{reason}</p>}

      <div className="space-y-3">
        {changes.persona_role && (
          <DiffRow label={t("orchestrator.update_persona_role")} before={current.persona_role} after={changes.persona_role} />
        )}
        {changes.persona_tone && (
          <DiffRow label={t("orchestrator.update_persona_tone")} before={current.persona_tone} after={changes.persona_tone} />
        )}
        {changes.capabilities && (
          <DiffRow label={t("orchestrator.update_capabilities")}
            before={current.capabilities.join(" · ")} after={changes.capabilities.join(" · ")} />
        )}
        {equipmentDelta.length > 0 && (
          <div className="space-y-1">
            <div className="text-[9.5px] font-mono uppercase tracking-widest text-subtle-foreground">
              {t("orchestrator.update_equipment")}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {equipmentDelta.map(({ key, add }) => (
                <span key={`${add ? "+" : "-"}${key}`}
                  className={`inline-flex items-center gap-0.5 text-[10.5px] font-mono px-2 py-0.5 rounded-lg ${
                    add ? "bg-success/15 text-success" : "bg-danger/15 text-danger line-through"}`}>
                  {add ? <Plus className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
                  {key}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button type="button" onClick={onConfirm}
          className="flex items-center gap-1.5 px-4 py-2 bg-primary hover:bg-primary-hover text-primary-foreground text-[11px] font-bold font-mono uppercase tracking-wider rounded-lg transition-all">
          <Check className="w-3.5 h-3.5" />
          {t("orchestrator.update_confirm")}
        </button>
        <button type="button" onClick={onDismiss}
          className="px-4 py-2 bg-surface-raised hover:bg-border text-muted-foreground text-[11px] font-mono uppercase rounded-lg border border-border-strong transition-all">
          {t("orchestrator.update_dismiss")}
        </button>
      </div>
    </div>
  );
}

import { useTranslation } from "react-i18next";
import type { Equipment, EquipmentItem } from "../../types";

const MAX_COMPACT = 4;

function provenanceKey(item: EquipmentItem): string {
  if (item.granted_by === "escalation") return "equipment.granted_escalation";
  if (item.granted_by === "user") return "equipment.granted_user";
  return "equipment.granted_create";
}

function Chip({ item, kind }: { item: EquipmentItem; kind: "toolset" | "skill" }) {
  const { t } = useTranslation();
  const tone =
    kind === "toolset"
      ? "border-sky-400/30 bg-sky-400/10 text-sky-200"
      : "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  return (
    <span
      title={t(provenanceKey(item))}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${tone}`}
    >
      <span aria-hidden>{kind === "toolset" ? "🔧" : "📘"}</span>
      {item.name}
      {item.grant === "temporary" && (
        <span className="rounded-full bg-amber/20 px-1.5 text-[10px] text-amber">
          {t("equipment.temp_badge")}
        </span>
      )}
    </span>
  );
}

export default function EquipmentChips({
  equipment,
  compact = false,
}: {
  equipment: Equipment;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const all = [
    ...equipment.toolsets.map((item) => ({ item, kind: "toolset" as const })),
    ...equipment.skills.map((item) => ({ item, kind: "skill" as const })),
  ];
  if (all.length === 0) return null;
  const shown = compact ? all.slice(0, MAX_COMPACT) : all;
  const hidden = all.length - shown.length;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {shown.map(({ item, kind }) => (
        <Chip key={`${kind}:${item.key}`} item={item} kind={kind} />
      ))}
      {hidden > 0 && (
        <span className="text-xs text-white/40">{t("equipment.more", { count: hidden })}</span>
      )}
    </div>
  );
}

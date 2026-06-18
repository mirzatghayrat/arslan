import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { SpawnSummary } from "../../types";
import EquipmentChips from "../arslan/EquipmentChips";

interface Props {
  spawn: SpawnSummary;
  onDelete: (id: number) => void;
}

export default function SpawnCard({ spawn, onDelete }: Props) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-center justify-between">
        <span className="font-medium text-amber">{spawn.name}</span>
        <span className="text-xs text-white/50">{t("dashboard.status_idle")}</span>
      </div>
      <span className="text-xs text-white/50">{spawn.domain}</span>
      {spawn.equipment && <EquipmentChips equipment={spawn.equipment} compact />}
      <div className="mt-2 flex gap-2">
        <Link
          to={`/chat/${spawn.id}`}
          className="rounded-lg bg-amber px-3 py-1.5 text-sm font-medium text-black"
        >
          {t("dashboard.open")}
        </Link>
        <button
          onClick={() => {
            if (window.confirm(t("dashboard.confirm_delete"))) onDelete(spawn.id);
          }}
          className="rounded-lg px-3 py-1.5 text-sm text-white/70 hover:bg-white/10"
        >
          {t("dashboard.delete")}
        </button>
      </div>
    </div>
  );
}

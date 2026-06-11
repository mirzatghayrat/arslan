import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../../api/client";
import type { RegistryCatalog, SpawnDetail } from "../../types";
import EquipmentChips from "../arslan/EquipmentChips";

export default function EquipmentPanel({
  spawn,
  onUpdated,
}: {
  spawn: SpawnDetail;
  onUpdated: (s: SpawnDetail) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [catalog, setCatalog] = useState<RegistryCatalog | null>(null);
  const [selToolsets, setSelToolsets] = useState<Set<string>>(new Set());
  const [selSkills, setSelSkills] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const equipment = spawn.equipment ?? { toolsets: [], skills: [] };
  const tempItems = [...equipment.toolsets, ...equipment.skills].filter(
    (i) => i.grant === "temporary",
  );

  const startEdit = async () => {
    setError(null);
    try {
      const cat = await api.getRegistry();
      setCatalog(cat);
      setSelToolsets(new Set(equipment.toolsets.filter((i) => i.grant === "permanent").map((i) => i.key)));
      setSelSkills(new Set(equipment.skills.filter((i) => i.grant === "permanent").map((i) => i.key)));
      setEditing(true);
    } catch {
      setError(t("errors.load_failed"));
    }
  };

  const toggle = (sel: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(sel);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setter(next);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateEquipment(spawn.id, {
        toolsets: [...selToolsets],
        skills: [...selSkills],
      });
      onUpdated(updated);
      setEditing(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("errors.save_failed"));
    } finally {
      setSaving(false);
    }
  };

  const row = (
    key: string, name: string, description: string, assignable: boolean,
    sel: Set<string>, setter: (s: Set<string>) => void,
  ) => (
    <label
      key={key}
      title={assignable ? description : t("equipment.locked")}
      className={`flex items-start gap-2 rounded-lg px-2 py-1.5 ${assignable ? "cursor-pointer hover:bg-white/5" : "opacity-40"}`}
    >
      <input
        type="checkbox"
        disabled={!assignable}
        checked={sel.has(key)}
        onChange={() => toggle(sel, setter, key)}
        className="mt-0.5"
      />
      <span className="text-sm">
        {name} {!assignable && <span aria-label={t("equipment.locked")}>🔒</span>}
        <span className="block text-xs text-white/40">{description}</span>
      </span>
    </label>
  );

  return (
    <div className="mb-3 rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{t("equipment.title")}</span>
        {!editing && (
          <button onClick={() => void startEdit()} className="text-xs text-amber hover:underline">
            {t("equipment.edit")}
          </button>
        )}
      </div>
      {!editing && (
        <div className="mt-2">
          {equipment.toolsets.length + equipment.skills.length === 0 ? (
            <span className="text-xs text-white/40">{t("equipment.empty")}</span>
          ) : (
            <EquipmentChips equipment={equipment} />
          )}
        </div>
      )}
      {editing && catalog && (
        <div className="mt-2 space-y-3">
          <div>
            <p className="mb-1 text-xs uppercase text-white/40">{t("equipment.toolsets")}</p>
            {catalog.toolsets.map((ts) =>
              row(ts.key, ts.name, ts.description, ts.assignable, selToolsets, setSelToolsets),
            )}
          </div>
          <div>
            <p className="mb-1 text-xs uppercase text-white/40">{t("equipment.skills")}</p>
            {catalog.skills.map((sk) =>
              row(sk.key, sk.name, sk.description, sk.assignable, selSkills, setSelSkills),
            )}
          </div>
          {tempItems.length > 0 && (
            <div>
              <p className="mb-1 text-xs uppercase text-white/40">{t("equipment.temporary")}</p>
              {tempItems.map((i) => (
                <p key={i.key} className="text-xs text-white/50">
                  {i.name} <span className="text-amber">({t("equipment.temp_badge")})</span>
                </p>
              ))}
            </div>
          )}
          {error && <p className="text-xs text-red-300">{error}</p>}
          <div className="flex gap-2">
            <button
              onClick={() => void save()}
              disabled={saving}
              className="rounded-lg bg-amber px-3 py-1.5 text-sm font-medium text-black disabled:opacity-50"
            >
              {t("equipment.save")}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="rounded-lg px-3 py-1.5 text-sm text-white/70 hover:bg-white/10"
            >
              {t("equipment.cancel")}
            </button>
          </div>
        </div>
      )}
      {!editing && error && <p className="mt-1 text-xs text-red-300">{error}</p>}
    </div>
  );
}

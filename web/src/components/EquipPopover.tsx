// EquipPopover — the per-row "equip to spawn…" affordance in the capability
// catalog. Opens a small inline popover listing spawns with checkboxes that
// reflect current equipment; toggling one does a REPLACE-semantics PUT
// (read the spawn's current user-managed toolset+skill keys, add/remove this
// one key, send BOTH lists back — never drop the other list). Optimistic UI
// with rollback + honest failure text on error.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { Equipment, EquipmentItem, SpawnSummary } from "../api/client.types";

/** Keys the user-equipment editor manages: permanent grants from create/user.
 * Temporary (escalation) grants are excluded — sending them in a replace PUT
 * would silently promote them to permanent. */
function userManagedKeys(items: EquipmentItem[] | undefined): string[] {
  return (items ?? [])
    .filter(
      (i) =>
        i.grant === "permanent" &&
        (i.granted_by === undefined || i.granted_by === "create" || i.granted_by === "user"),
    )
    .map((i) => i.key);
}

export default function EquipPopover({ kind, capKey }: { kind: "toolset" | "skill"; capKey: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [spawns, setSpawns] = useState<SpawnSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const listKey = kind === "toolset" ? "toolsets" : "skills";

  useEffect(() => {
    if (!open) return;
    let alive = true;
    api
      .listSpawns()
      .then((s) => { if (alive) setSpawns(s); })
      .catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, [open]);

  const isEquipped = (sp: SpawnSummary) =>
    (sp.equipment?.[listKey] ?? []).some((i) => i.key === capKey);

  const toggle = async (sp: SpawnSummary) => {
    if (busyId !== null || !spawns) return;
    const prev = spawns;
    const eq = sp.equipment;
    const toolsets = userManagedKeys(eq?.toolsets);
    const skills = userManagedKeys(eq?.skills);
    const had = isEquipped(sp);
    const mutate = (keys: string[]) =>
      had ? keys.filter((k) => k !== capKey) : [...keys.filter((k) => k !== capKey), capKey];
    const body =
      kind === "toolset"
        ? { toolsets: mutate(toolsets), skills }
        : { toolsets, skills: mutate(skills) };

    // Optimistic flip of just this spawn's checkbox state.
    const optimistic: Equipment = {
      toolsets: eq?.toolsets ?? [],
      skills: eq?.skills ?? [],
      [listKey]: had
        ? (eq?.[listKey] ?? []).filter((i) => i.key !== capKey)
        : [
            ...(eq?.[listKey] ?? []),
            { key: capKey, name: capKey, status: "registered", grant: "permanent" as const, granted_by: "user" as const },
          ],
    };
    setError(null);
    setBusyId(sp.id);
    setSpawns(prev.map((s) => (s.id === sp.id ? { ...s, equipment: optimistic } : s)));
    try {
      const detail = await api.updateEquipment(sp.id, body);
      setSpawns((cur) =>
        (cur ?? []).map((s) =>
          s.id === sp.id ? { ...s, equipment: detail.equipment ?? optimistic } : s,
        ),
      );
    } catch {
      setSpawns(prev); // rollback the optimistic flip
      setError(t("capabilities.equip.error"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className="text-[10px] font-mono text-primary hover:underline whitespace-nowrap"
      >
        {t("capabilities.equip.action")}
      </button>
      {open && (
        <>
          {/* click-away layer */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            role="dialog"
            className="absolute right-0 z-50 mt-1 w-60 max-h-64 overflow-y-auto bg-surface-raised border border-border-strong rounded-lg shadow-lg p-2"
          >
            {error && <div className="text-[10px] text-danger font-mono mb-1">{error}</div>}
            {!spawns && !error && (
              <div className="text-[10px] text-subtle-foreground">{t("capabilities.equip.loading")}</div>
            )}
            {spawns && spawns.length === 0 && (
              <div className="text-[10px] text-subtle-foreground">{t("capabilities.equip.empty")}</div>
            )}
            {spawns?.map((sp) => (
              <label
                key={sp.id}
                className="flex items-center gap-2 px-1 py-1 text-[11px] text-foreground cursor-pointer hover:bg-surface rounded"
              >
                <input
                  type="checkbox"
                  checked={isEquipped(sp)}
                  disabled={busyId !== null}
                  onChange={() => toggle(sp)}
                />
                <span className="truncate">{sp.name}</span>
              </label>
            ))}
          </div>
        </>
      )}
    </span>
  );
}

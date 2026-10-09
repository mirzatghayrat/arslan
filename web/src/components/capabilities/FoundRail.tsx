import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi, type CapabilityFind } from "../../api/capabilities";
import CandidateDossier from "./CandidateDossier";

/**
 * "Arslan 找到的" (0.1.57 §4, board Capabilities-v3 right rail): what Arslan found and kept
 * for later — a card you said not now to, a background job that hit a wall, a project level
 * that may need something. Each says why it looked, what it found and its license. Never a
 * notification; Arslan only proposes and never installs from here by itself.
 */
export default function FoundRail({ onChanged }: { onChanged?: () => void }) {
  const { t } = useTranslation();
  const [finds, setFinds] = useState<CapabilityFind[] | null>(null);
  const [open, setOpen] = useState<CapabilityFind | null>(null);
  const load = useCallback(async () => {
    try { setFinds(await capabilitiesApi.finds()); } catch { setFinds([]); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function dismiss(id: string) {
    await capabilitiesApi.dismissFind(id).catch(() => {});
    await load();
    onChanged?.();
  }
  return (
    <aside className="flex flex-col gap-2" data-testid="found-rail" aria-label={t("discover.rail_title")}>
      <h3 className="px-1 text-[12px] font-semibold text-muted-foreground">
        {t("discover.rail_title")} <span className="font-mono">{finds?.length ?? ""}</span></h3>
      {finds && finds.length === 0 && <p className="rounded-xl border border-dashed border-border px-3 py-3 text-[12px] text-muted-foreground">
        {t("discover.rail_none")}</p>}
      {finds?.map(f => (
        <div key={f.id} data-testid={`find-${f.id}`} className="flex flex-col gap-1 rounded-xl border border-border bg-background px-3 py-2.5">
          <div className="flex items-start gap-2">
            <span className="min-w-0 flex-1 text-[12.5px] font-semibold leading-snug">{t(`discover.rail_why_${f.why}`, { need: f.need })}</span>
            <button type="button" aria-label={t("discover.rail_dismiss")} data-testid={`find-dismiss-${f.id}`}
              className="text-subtle-foreground hover:text-foreground" onClick={() => void dismiss(f.id)}><X size={13} /></button>
          </div>
          <span className="text-[12px] text-muted-foreground">{t("discover.rail_found", { name: f.candidate.name })}</span>
          <span className="flex items-center gap-2">
            <span className="rounded-full bg-success/10 px-[7px] py-0.5 text-[11px] text-success">{f.candidate.license.spdx ?? "?"}</span>
            <button type="button" className="ml-auto text-[12px] font-semibold hover:underline" onClick={() => setOpen(f)}
              data-testid={`find-open-${f.id}`}>{t("discover.look")}</button>
          </span>
        </div>
      ))}
      <p className="px-1 text-[11px] text-subtle-foreground">{t("discover.rail_footer")}</p>
      {open && <CandidateDossier candidate={open.candidate} onClose={() => setOpen(null)}
        onInstalled={() => { void load(); onChanged?.(); }} />}
    </aside>
  );
}

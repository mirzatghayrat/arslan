import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Globe, KeyRound, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi, type CapabilityRow } from "../api/capabilities";
import { openSection } from "../lib/sections";
import { Button, Notice } from "./kit";

const GROUPS = ["mac", "work", "research", "methods"] as const;
type Filter = "all" | "on" | "canTurnOn";
/** Built-in details that are a note to show (others, like a runtime name, feed the reason). */
const NOTES = new Set(["own_folder_only", "first_use_setup"]);
const FOLD_AFTER = 6;
const DOT = { on: "bg-[#34C759]", off: "bg-subtle-foreground", setup: "bg-ask", na: "bg-subtle-foreground" } as const;

/**
 * What Arslan can do, as switches (0.1.55 §14, board Capabilities-v2). Every row comes
 * from GET /capabilities, which reads the same gates the model's tool list is built
 * from: a switch here is the switch, not a second opinion about it.
 */
export default function CapabilitySwitches({ onOpenTab }: { onOpenTab?: (tab: "mcps" | "discover" | "forge") => void }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<CapabilityRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const load = useCallback(async () => {
    try { setRows(await capabilitiesApi.list()); setFailed(false); }
    catch { setFailed(true); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function flip(row: CapabilityRow, on: boolean) {
    setBusy(row.key); setError(null);
    try {
      const next = await capabilitiesApi.switch(row.key, on);
      setRows(old => old?.map(r => (r.key === row.key ? { ...r, ...next } : r)) ?? old);
    } catch { setError(t("capabilityList.failed")); }
    finally { setBusy(null); }
  }
  function fix(row: CapabilityRow) {
    const [what, where] = (row.fix ?? "").split(":");
    if (what === "open_settings") openSection("settings", where);
    else onOpenTab?.("mcps");
  }

  const name = (row: CapabilityRow) => row.name ?? t(`capabilityList.${row.key}_name`);
  const what = (row: CapabilityRow) => row.source === "builtin" ? t(`capabilityList.${row.key}_what`) : (row.detail && row.source === "skill" ? row.detail : "");
  const reason = (row: CapabilityRow) => row.reason
    ? t(`capabilityList.reason_${row.reason}`, { detail: row.detail ?? "Node.js", defaultValue: row.reason }) : "";
  const all = rows ?? [];
  const counts = { on: all.filter(r => r.state === "on").length, canTurnOn: all.filter(r => r.state === "off" || r.state === "setup").length };
  const shown = all.filter(r => filter === "all" || (filter === "on" ? r.state === "on" : r.state === "off" || r.state === "setup"));

  const row = (r: CapabilityRow) => {
    const switchable = r.switch !== null && (r.state === "on" || r.state === "off");
    return <div key={r.key} data-testid={`cap-${r.key}`} data-state={r.state}
      className={`flex items-center gap-3 border-t border-border px-4 py-2.5 first:border-t-0 ${r.state === "na" ? "opacity-55" : ""}`}>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex flex-wrap items-center gap-2 text-[14px]">{name(r)}
          <span className="inline-flex items-center gap-1 text-[11px] text-subtle-foreground">
            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${DOT[r.state]}`} />{t(`capabilityList.state_${r.state}`)}</span></span>
        <span className="text-[12px] text-subtle-foreground">
          {[what(r), t(`capabilityList.source_${r.source}`)].filter(Boolean).join(" · ")}
          {r.source === "builtin" && r.detail && NOTES.has(r.detail) ? <> · {t(`capabilityList.detail_${r.detail}`)}</> : null}
          {r.state === "setup" && r.reason === "mcp_error" && r.detail ? <> · <span className="font-mono">{r.detail}</span></> : null}
        </span>
      </div>
      {switchable ? <input type="checkbox" role="switch" className="kit-switch" aria-label={name(r)} data-testid={`cap-switch-${r.key}`}
        checked={r.state === "on"} disabled={busy === r.key} onChange={event => void flip(r, event.target.checked)} />
        : r.state === "setup" ? <Button size="sm" data-testid={`cap-fix-${r.key}`} onClick={() => fix(r)}>{reason(r)}</Button>
        : r.state === "na" ? <span className="shrink-0 text-[12px] text-subtle-foreground">{reason(r)}</span> : null}
    </div>;
  };

  return <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
    <div className="flex min-w-0 max-w-[720px] flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-xl text-[13px] text-muted-foreground">{t("capabilityList.intro")}</p>
        <div role="group" className="inline-flex rounded-lg bg-fill p-0.5">
          {(["all", "on", "canTurnOn"] as const).map(key => <button key={key} aria-pressed={filter === key} data-testid={`cap-filter-${key}`}
            className={`rounded-md px-2.5 py-1 text-[12px] ${filter === key ? "bg-background font-semibold text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => setFilter(key)}>{key === "all" ? t("capabilityList.filterAll")
              : t(key === "on" ? "capabilityList.filterOn" : "capabilityList.filterCanTurnOn", { count: counts[key] })}</button>)}
        </div>
      </div>
      {failed && <Notice tone="error" role="alert">{t("capabilityList.loadFailed")}</Notice>}
      {error && <Notice tone="error" role="alert">{error}</Notice>}
      {rows && GROUPS.map(group => {
        const inGroup = shown.filter(r => r.group === group);
        if (!inGroup.length) return null;
        // A long group (dozens of methods) opens with its first few; the rest one click away.
        const folded = inGroup.length > FOLD_AFTER && !openGroups.has(group);
        return <section key={group} data-testid={`cap-group-${group}`} className="flex flex-col gap-1.5">
          <h2 className="flex items-baseline px-1 text-[12px] font-semibold text-muted-foreground">{t(`capabilityList.group_${group}`)}
            {inGroup.length > FOLD_AFTER && <button data-testid={`cap-more-${group}`} aria-expanded={!folded}
              className="ml-auto font-normal hover:text-foreground"
              onClick={() => setOpenGroups(old => { const next = new Set(old); if (next.has(group)) next.delete(group); else next.add(group); return next; })}>
              {folded ? `${t("memoryPage.showAll", { count: inGroup.length })} ›` : t("memoryPage.showFewer")}</button>}</h2>
          <div className="overflow-hidden rounded-xl border border-border bg-surface">{(folded ? inGroup.slice(0, FOLD_AFTER) : inGroup).map(row)}</div>
        </section>;
      })}
    </div>
    <aside className="flex w-full shrink-0 flex-col gap-2 lg:w-[300px]">
      <h2 className="px-1 text-[12px] font-semibold text-muted-foreground">{t("capabilityList.addTitle")}</h2>
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {([["mcps", Globe, "addMcp"], ["discover", KeyRound, "addLink"], ["forge", Sparkles, "addMethod"]] as const).map(([tab, Icon, key]) =>
          <button key={tab} data-testid={`cap-add-${tab}`} onClick={() => onOpenTab?.(tab)}
            className="flex w-full items-center gap-2.5 border-t border-border px-3.5 py-2.5 text-left first:border-t-0 hover:bg-fill">
            <Icon size={14} className="shrink-0 text-subtle-foreground" />
            <span className="flex min-w-0 flex-1 flex-col"><span className="text-[13px]">{t(`capabilityList.${key}`)}</span>
              <span className="text-[12px] text-subtle-foreground">{t(`capabilityList.${key}What`)}</span></span>
            <ChevronRight size={14} className="text-subtle-foreground" />
          </button>)}
      </div>
      <p className="px-1 text-[12px] leading-relaxed text-subtle-foreground">{t("capabilityList.addFoot")}</p>
    </aside>
  </div>;
}

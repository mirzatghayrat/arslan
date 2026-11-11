import { useTranslation } from "react-i18next";
import type { CapabilityRow, PluginPart } from "../../api/capabilities";
import { Button } from "../kit";
import { PluginHooks } from "./PluginHooks";

/**
 * What a plugin holds (CAP7b, board Group): each skill and connection, with its state or when it was last used. None
 * has a switch or a delete of its own: the plugin's row is the one. A connection waiting for its sign-in opens its own
 * card, where Authorize is. Then its hooks, each with its own switch (HOOK-4, `PluginHooks`).
 */
export function PluginParts({ row, used, onOpenPart }: {
  row: CapabilityRow; used: (iso: string | null) => string; onOpenPart: (part: PluginPart) => void;
}) {
  const { t } = useTranslation();
  return <div data-testid={`plugin-parts-${row.key}`} className="flex flex-col gap-1 rounded-lg bg-fill/60 px-3 py-2">
    {(row.parts ?? []).map(p => <div key={p.key} data-testid={`plugin-part-${p.key}`} className="flex items-center gap-2 text-[12.5px]">
      <span className="rounded-md bg-background px-1.5 py-px text-[11px] text-muted-foreground">
        {t(p.kind === "skill" ? "capabilityList.kind_skill" : "capabilityList.part_connection")}</span>
      <bdi className="min-w-0 truncate">{p.name ?? p.key}</bdi>
      <span className="ml-auto shrink-0 text-[11.5px] text-subtle-foreground">
        {p.reason ? t(`capabilityList.reason_${p.reason}`, { detail: p.detail ?? "", defaultValue: p.reason })
          : p.state === "off" ? t("capabilityList.state_off") : used(p.last_used)}</span>
      {p.reason === "needs_sign_in" && <Button size="sm" data-testid={`plugin-part-open-${p.key}`} onClick={() => onOpenPart(p)}>
        {t("capabilityList.plugin_signIn")}</Button>}
    </div>)}
    <PluginHooks row={row} />
  </div>;
}

/** A part as a row of its own, for its details sheet only (its sign-in): never switched or deleted there. */
export const partRow = (p: PluginPart): CapabilityRow => ({
  key: p.key, section: p.kind === "skill" ? "skills" : "connections", origin: "installed", deletable: false,
  last_used: p.last_used, source_id: p.source_id, reach: null, state: p.state, tools: [], switch: null, reason: p.reason,
  fix: p.fix, name: p.name, detail: p.detail,
});

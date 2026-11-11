import { useState } from "react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi, type CapabilityRow } from "../../api/capabilities";
import type { HookActivity, HookRow } from "../../api/client.types";
import { Escaped } from "../../lib/outsideText";
import { commandLine, hookMatch, hookWhen, runs } from "./HooksRow";

type T = (key: string, options?: Record<string, unknown>) => string;

/** The plugin's own folder, as `…`: the switch row has room for the rest of the command line. */
const short = (hook: HookRow) => commandLine(hook).replace(/\$\{?CLAUDE_(PLUGIN_ROOT|SKILL_DIR)\}?/g, "…");

/** HOOK-3's last-activity line; none when nothing was recorded (nothing records it before HOOK-3). */
function lastLine(t: T, last: HookActivity | null | undefined, on: boolean): { text: string; tone: string } | null {
  const off = (text: string) => on ? text : `${t("capabilityList.state_off")} · ${text}`;
  if (!last) return null;
  if (last.blocked) return { text: off(t(`capabilityList.hookLast_${last.blocked}`)), tone: "text-ask" };
  if (last.stopped_today > 0) {
    return { text: off(t("capabilityList.hookLast_stopped", { count: last.stopped_today })), tone: "text-danger" };
  }
  if (last.ran_today > 0) {
    return { text: off(t("capabilityList.hookLast_ran", { count: last.ran_today })), tone: "text-muted-foreground" };
  }
  return null;
}

/**
 * A plugin's hooks under "Show what's inside" (HOOK-4, board 8, B): one row per hook Arslan runs, with when it runs and
 * on what, its command, what it did lately, and its own switch, stored by HOOK-1 (PUT /capability-hooks). Hooks that
 * don't run have no switch here: their card said so.
 */
export function PluginHooks({ row }: { row: CapabilityRow }) {
  const { t } = useTranslation();
  const [switched, setSwitched] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const hooks = (row.hooks ?? []).filter(runs);
  if (!hooks.length || !row.source_id) return null;
  const flip = async (hook: HookRow, on: boolean) => {
    setBusy(hook.id);
    setFailed(false);
    try {
      const done = await capabilitiesApi.switchHook(`plugin:${row.source_id}`, hook.id, on);
      setSwitched(prev => ({ ...prev, [hook.id]: done.on }));
    } catch {
      setFailed(true);
    } finally {
      setBusy(null);
    }
  };
  return <div data-testid={`plugin-hooks-${row.key}`} className="flex flex-col">
    {hooks.map(hook => {
      const on = switched[hook.id] ?? hook.on;
      const when = hookWhen(t, hook.event), match = hookMatch(t, hook);
      const last = lastLine(t, hook.last, on);
      return <div key={hook.id} data-testid={`plugin-hook-${hook.id}`}
        className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border py-1.5 text-[12.5px]">
        <span className="flex min-w-0 flex-col gap-px">
          <span><span className="font-semibold">{when}</span><span className="text-muted-foreground"> · <bdi>{match}</bdi></span></span>
          <span className="text-[12px] text-muted-foreground [overflow-wrap:anywhere]"><Escaped text={short(hook)} /></span>
          {last && <span data-testid="plugin-hook-last" className={`text-[12px] ${last.tone}`}>{last.text}</span>}
        </span>
        <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-[12px] text-muted-foreground">
          <input type="checkbox" role="switch" className="kit-switch" checked={on} disabled={busy === hook.id}
            aria-label={t("capabilityList.hookSwitchLabel", { when, match })} data-testid={`plugin-hook-switch-${hook.id}`}
            onChange={event => void flip(hook, event.target.checked)} />
          <span>{t(on ? "capabilityList.state_on" : "capabilityList.state_off")}</span>
        </label>
      </div>;
    })}
    {failed && <span role="alert" className="pt-1 text-[12px] text-danger">{t("capabilityList.hookSwitchFailed")}</span>}
    <span className="pt-2 text-[12px] text-muted-foreground">{t("capabilityList.hookChangeNote")}</span>
  </div>;
}

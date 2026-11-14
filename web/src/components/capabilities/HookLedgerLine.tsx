import { useTranslation } from "react-i18next";
import { Escaped, isolate } from "../../lib/outsideText";
import { hookWhen } from "./HooksRow";

/**
 * One line of a run's ledger that a hook caused (docs/plans/0164/HOOK-plugin-hooks.md, rule 5): it stopped the call, or
 * Arslan asked you because of it. HOOK-3 emits these; nothing does yet, so nothing mounts this line before it.
 */
export interface HookLedgerEntry {
  kind: "hook_stopped" | "hook_asked";
  /** The Arslan tool and the call's argument as the ledger shows it (the command, the path). */
  tool: string;
  argument: string;
  /** The plugin, and the hook's event (one of the five Arslan runs). */
  plugin: string;
  event: string;
  /** The hook's own words, outside text; null: it didn't answer in 10 seconds, so Arslan asked you. */
  reason: string | null;
}

/** HOOK-4, board 8, C: "Stopped by a hook" or "Asked you", the tool and its argument; then the plugin, the event, and
 *  the hook's reason or its silence. The plugin's name and the reason come from outside, so neither can reorder the
 *  sentence around them. */
export function HookLedgerLine({ entry }: { entry: HookLedgerEntry }) {
  const { t } = useTranslation();
  const stopped = entry.kind === "hook_stopped";
  const said = { plugin: isolate(entry.plugin), when: hookWhen(t, entry.event) };
  return <div data-testid="hook-ledger-line" data-kind={entry.kind} className="flex flex-col gap-0.5 text-[13px] leading-snug">
    <span>
      <span className={`rounded-md px-1.5 py-px text-[11px] ${stopped ? "bg-danger/10 text-danger" : "bg-ask-soft text-ask"}`}>
        {t(stopped ? "capabilityList.hookLedger_stopped" : "capabilityList.hookLedger_asked")}</span>{" "}
      <bdi>{entry.tool}</bdi> <code className="font-mono text-[12px]"><Escaped text={entry.argument} /></code>
    </span>
    <span className="text-[12px] text-muted-foreground">
      {entry.reason == null ? t("capabilityList.hookLedger_timeout", said)
        : t("capabilityList.hookLedger_reason", { ...said, reason: isolate(entry.reason) })}</span>
  </div>;
}

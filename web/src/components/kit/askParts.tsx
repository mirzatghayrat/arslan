import type { ReactNode } from "react";
import type { TFunction } from "i18next";
import { appleScriptRisk } from "../../lib/scriptRisk";

/** A context line's icon, sized like the mock (15px, secondary label colour). */
export const lineIcon = (Icon: (p: { className?: string; "aria-hidden"?: boolean }) => ReactNode) =>
  <Icon className="h-[15px] w-[15px] shrink-0" aria-hidden />;

/** "这段脚本会删除东西（第 2 行：delete）· 以代码为准", from the code, or null when it only reads. */
export function scriptRiskLine(code: string, t: TFunction): string | null {
  const r = appleScriptRisk(code);
  if (!r) return null;
  if (!r.effects.length) return t("kit.riskUnknown");
  return t("kit.riskLine", {
    what: r.effects.map((e) => t(`kit.risk.${e}`)).join(t("kit.riskJoin")),
    lines: r.lines.join(", "), words: r.words.join(", "),
  });
}

/** Fingerprints of another machine, for a person to compare against the machine itself. */
export function Fingerprints({ label, list, testId }: { label: string; list: string[]; testId: string }) {
  if (!list.length) return null;
  return (
    <div data-testid={testId} className="flex flex-col gap-1 rounded-[10px] bg-surface-raised px-3 py-2.5">
      <span className="text-[12px] text-muted-foreground">{label}</span>
      {list.map((fp) => <code key={fp} className="break-all font-mono text-[11.5px] text-foreground">{fp}</code>)}
    </div>
  );
}

/** A checkbox option under the card ("don't ask again …"). */
export function AskOption({ checked, onChange, label, testId }:
  { checked: boolean; onChange: (v: boolean) => void; label: string; testId: string }) {
  return (
    <label className="flex items-start gap-2 text-[13px] text-muted-foreground">
      <input type="checkbox" data-testid={testId} checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="mt-[3px] accent-foreground" />
      <span>{label}</span>
    </label>
  );
}

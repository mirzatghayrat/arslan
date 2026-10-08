import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Band, Level } from "../../api/projects";
import { BAND_DOT } from "./projectUi";

const BANDS: Band[] = ["shaping", "doing", "done"];
const input = "w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-foreground/40";

/**
 * Edit a plan's levels (0.1.56 §3): rename, reorder, remove, add; each level's band says
 * which board column it counts for. Cleared levels are history and stay read-only.
 */
export default function PlanEditor({ levels, onChange }: { levels: Level[]; onChange: (next: Level[]) => void }) {
  const { t } = useTranslation();
  const set = (i: number, patch: Partial<Level>) => onChange(levels.map((lv, k) => (k === i ? { ...lv, ...patch } : lv)));
  const move = (i: number, by: number) => {
    const j = i + by;
    if (j < 0 || j >= levels.length || levels[j].state === "cleared") return;
    const next = [...levels];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  return (
    <div className="flex flex-col gap-2" data-testid="plan-editor">
      <ol className="overflow-hidden rounded-xl border border-border bg-background">
        {levels.map((lv, i) => {
          const locked = lv.state === "cleared";
          return (
            <li key={lv.id ?? `new-${i}`} data-testid={`plan-level-${i}`} className="flex items-stretch gap-3 border-t border-border py-2 pr-2 first:border-t-0">
              <span aria-hidden="true" className={`w-[3px] shrink-0 rounded-r ${BAND_DOT[lv.band]}`} />
              <span className="w-4 shrink-0 pt-1.5 font-mono text-[12px] text-subtle-foreground">{i + 1}</span>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <input className={`${input} min-w-32 flex-1 font-medium`} value={lv.name} disabled={locked} maxLength={120}
                    aria-label={t("projectsUI.levelName")} onChange={e => set(i, { name: e.target.value })} />
                  <select className="rounded-lg border border-border bg-background px-2 py-1.5 text-[12px]" value={lv.band} disabled={locked}
                    aria-label={t("projectsUI.band")} onChange={e => set(i, { band: e.target.value as Band })}>
                    {BANDS.map(b => <option key={b} value={b}>{t(`projectsUI.col_${b}`)}</option>)}
                  </select>
                  {lv.habit && <span className="rounded-full bg-ask-soft px-2 py-0.5 text-[11px] text-ask">{t("projectsUI.habitLevel")}</span>}
                  {locked && <span className="text-[11px] text-subtle-foreground">{t("projectsUI.clearedLocked")}</span>}
                </div>
                {!locked && <input className={input} value={lv.clear_condition ?? ""} maxLength={400}
                  placeholder={t("projectsUI.clearConditionPh")} aria-label={t("projectsUI.clearCondition")}
                  onChange={e => set(i, { clear_condition: e.target.value })} />}
                {!locked && <div className="flex flex-col gap-1 pl-1">
                  {lv.checkpoints.map((cp, k) => (
                    <div key={cp.id ?? `cp-${k}`} className="flex items-center gap-1.5">
                      <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-fill-strong" />
                      <input className={`${input} py-1 text-[12.5px]`} value={cp.text} maxLength={200} placeholder={t("projectsUI.checkpointPh")}
                        aria-label={t("projectsUI.checkpointPh")}
                        onChange={e => set(i, { checkpoints: lv.checkpoints.map((c, n) => (n === k ? { ...c, text: e.target.value } : c)) })} />
                      <button type="button" aria-label={t("projectsUI.remove")} className="text-subtle-foreground hover:text-foreground"
                        onClick={() => set(i, { checkpoints: lv.checkpoints.filter((_, n) => n !== k) })}><X size={13} /></button>
                    </div>))}
                  {lv.checkpoints.length < 12 && <button type="button" className="self-start text-[12px] text-muted-foreground hover:text-foreground"
                    onClick={() => set(i, { checkpoints: [...lv.checkpoints, { text: "" }] })}>+ {t("projectsUI.addCheckpoint")}</button>}
                </div>}
              </div>
              {!locked && <div className="flex shrink-0 flex-col items-center gap-0.5">
                <button type="button" aria-label={t("projectsUI.moveUp")} disabled={i === 0} className="text-subtle-foreground hover:text-foreground disabled:opacity-30"
                  onClick={() => move(i, -1)}><ArrowUp size={14} /></button>
                <button type="button" aria-label={t("projectsUI.moveDown")} disabled={i === levels.length - 1} className="text-subtle-foreground hover:text-foreground disabled:opacity-30"
                  onClick={() => move(i, 1)}><ArrowDown size={14} /></button>
                <button type="button" aria-label={t("projectsUI.remove")} disabled={levels.filter(l => l.state !== "cleared").length <= 1}
                  className="text-subtle-foreground hover:text-destructive disabled:opacity-30" onClick={() => onChange(levels.filter((_, k) => k !== i))}><X size={14} /></button>
              </div>}
            </li>
          );
        })}
      </ol>
      {levels.length < 15 && <button type="button" data-testid="plan-add-level" className="inline-flex items-center gap-1.5 self-start text-[12.5px] text-muted-foreground hover:text-foreground"
        onClick={() => onChange([...levels, { name: "", band: levels[levels.length - 1]?.band === "done" ? "doing" : (levels[levels.length - 1]?.band ?? "shaping"), checkpoints: [] }])}>
        <Plus size={13} />{t("projectsUI.addLevel")}</button>}
      <p className="text-[12px] text-subtle-foreground">{t("projectsUI.bandHint")}</p>
    </div>
  );
}

/** What the server accepts: no blank names or checkpoints. */
export function planIsValid(levels: Level[]): boolean {
  return levels.length > 0 && levels.every(lv => lv.name.trim() && lv.checkpoints.every(cp => cp.text.trim()));
}

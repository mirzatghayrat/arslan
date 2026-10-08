import { Check, Flag } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Band, Level } from "../../api/projects";
import { BAND_DOT, BAND_SOFT } from "./projectUi";

/**
 * The level map (0.1.56 §1, board Project-LevelMap): levels left to right like stages in a
 * game — cleared ✓, the current one large, the rest numbered, the last one a flag — with
 * the bands (Shaping / Doing / Done) drawn above as the columns they count for.
 */
export default function LevelMap({ levels }: { levels: Level[] }) {
  const { t } = useTranslation();
  const runs: { band: Band; from: number; to: number }[] = [];
  levels.forEach((lv, i) => {
    const last = runs[runs.length - 1];
    if (last && last.band === lv.band) last.to = i; else runs.push({ band: lv.band, from: i, to: i });
  });
  const cols = `repeat(${levels.length}, minmax(0, 1fr))`;
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-background px-4 pb-3 pt-2.5" data-testid="level-map">
      <div className="grid min-w-[520px] gap-y-2" style={{ gridTemplateColumns: cols }}>
        {runs.map(run => <span key={run.from} className={`flex h-5 items-center rounded-full px-2.5 text-[11px] font-semibold ${BAND_SOFT[run.band]}`}
          style={{ gridColumn: `${run.from + 1} / ${run.to + 2}`, gridRow: 1 }}>
          <span aria-hidden="true" className={`mr-1.5 h-1.5 w-1.5 rounded-full ${BAND_DOT[run.band]}`} />{t(`projectsUI.col_${run.band}`)}</span>)}
        {levels.map((lv, i) => {
          const last = i === levels.length - 1;
          return (
            <div key={lv.id ?? i} style={{ gridRow: 2 }} data-testid={`level-node-${i}`} data-state={lv.state}
              className="relative flex flex-col items-center gap-1.5 pt-1">
              {i > 0 && <span aria-hidden="true" className={`absolute right-1/2 top-[22px] h-[3px] w-full -translate-y-1/2 ${lv.state === "todo" ? "bg-fill-strong" : "bg-foreground"}`} />}
              <span className={`relative z-10 flex items-center justify-center rounded-full ${lv.state === "current"
                ? "h-9 w-9 bg-info-strong font-bold text-white ring-4 ring-info-soft"
                : lv.state === "cleared" ? "h-8 w-8 bg-foreground text-background" : "h-8 w-8 border border-border bg-background text-subtle-foreground"} text-[13px]`}>
                {lv.state === "cleared" ? <Check size={15} strokeWidth={2.6} /> : last && lv.state === "todo" ? <Flag size={14} className="text-success" /> : i + 1}
              </span>
              <span className={`max-w-full truncate px-1 text-center text-[12px] ${lv.state === "current" ? "font-bold"
                : lv.state === "todo" ? "text-subtle-foreground" : ""}`} title={lv.name}>{lv.name}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

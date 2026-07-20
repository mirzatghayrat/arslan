import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { GraphNodeDto } from "../../api/client";
import { startedAt } from "./temporal";

interface Props {
  nodes: GraphNodeDto[];
  /** ISO instant, or null = home position = no filtering at all */
  value: string | null;
  onChange: (v: string | null) => void;
  className?: string;
}

const DAY = 86_400_000;

/**
 * F1 — filter the graph by start time.
 *
 * 🔴 NAMING. This is called 「按生效时刻筛选」 and never 时间轴 / 历史 / 回放 / 快照.
 * It filters rows that STILL EXIST by a recorded start time. It is not a picture of
 * the past, because the past is not stored:
 *
 *   - hard deletes leave nothing behind (memory.py:392-405, fact_dedup.py:152/:181,
 *     brain.py:745, note_service.py:95, collections.py:80/:147) — a fact you deleted
 *     yesterday is absent from every past instant, with no marker
 *   - content is edited in place (memory.py:378-386, note_service.py:78-88), so a past
 *     instant renders TODAY's text under an old timestamp
 *   - accepting a delete_suspect nulls superseded_by (brain.py:727-740), erasing the
 *     record that a supersede happened at all
 *   - a belief's END is derived from its successor's valid_from, never recorded — there
 *     is no superseded_at column anywhere (see temporal.ts)
 *
 * The one-line caption below is load-bearing, not decoration. A code comment and a
 * delivery note satisfy the letter of the partial-fix rule, but the person dragging
 * this slider will read neither; the caption is the only disclosure that travels with
 * the feature. It renders whenever the control is off its home position.
 */
export default function BrainAsOfSlider({ nodes, value, onChange, className }: Props) {
  const { t } = useTranslation();

  // the span the data actually covers — a slider wider than the data is a lie about
  // how much there is to see
  // 🔴 Snapped to whole days. An <input type=range> only permits values of
  // min + k*step, so with raw utcnow() endpoints and step=DAY the rightmost REACHABLE
  // value is strictly less than max — `ms >= max` would never fire and the home
  // position would be unreachable by dragging, stranding the user in a filtered view
  // with no way back.
  const { min, max } = useMemo(() => {
    const ts = nodes.map(startedAt).filter((x): x is number => x != null);
    if (ts.length === 0) return { min: 0, max: 0 };
    return {
      min: Math.floor(Math.min(...ts) / DAY) * DAY,
      max: Math.ceil(Math.max(...ts) / DAY) * DAY,
    };
  }, [nodes]);

  const usable = max > min;
  const current = value ? Date.parse(value) : max;
  const atHome = value == null;

  if (!usable) return null;

  return (
    <div className={className} data-testid="asof-slider">
      <div className="flex items-center gap-2">
        <label className="whitespace-nowrap text-[11px] text-subtle-foreground" htmlFor="asof">
          {t("brain.temporal.asOfLabel")}
        </label>
        <input
          id="asof"
          type="range"
          className="flex-1"
          min={min}
          max={max}
          step={DAY}
          value={current}
          data-testid="asof-range"
          onChange={(e) => {
            const ms = Number(e.target.value);
            // snapping back to the far right returns to "show everything", which is a
            // different state from "as-of the newest instant" — the latter still hides
            // anything whose clock is null-free and later within the same day bucket
            onChange(ms >= max ? null : new Date(ms).toISOString());
          }}
        />
        <span className="w-24 shrink-0 font-mono text-[10px] text-subtle-foreground"
          data-testid="asof-value">
          {atHome ? t("brain.temporal.asOfAll") : new Date(current).toISOString().slice(0, 10)}
        </span>
      </div>
      {!atHome && (
        <div className="mt-1 text-[10px] text-warning" data-testid="asof-caveat" role="note">
          {t("brain.temporal.asOfCaveat")}
        </div>
      )}
    </div>
  );
}

import { memo, useEffect, useMemo, useState } from "react";
import { api, type BrainLeaf, type BrainUsageEventsDto } from "../../api/client";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";

/** D 活跃时间条 — one row per entity, one tick per recorded use.
 *
 * 🔴 Three honesty problems are structural here, not cosmetic, because an empty region
 * of a raster is a POSITIVE CLAIM ("nothing happened then") and every one of these would
 * make that claim falsely:
 *
 *  1. COVERAGE. `brain_usage.record` has three call sites — material, learning, note.
 *     There is no `record("profile", ...)` anywhere in the repo, so profile facts produce
 *     no events. Drawing them as empty rows would be pixel-identical to "never used", so
 *     they are NOT DRAWN AS ROWS AT ALL; the backend's `covered_kinds` drives an explicit
 *     note instead. A paragraph under the chart cannot undo a row of blank pixels.
 *  2. WINDOW. The endpoint defaults to SEVEN days. A month grid fed by the default would
 *     render three empty weeks as a quiet period, so `since` is always passed explicitly
 *     and `window_start` is drawn as the hard left edge.
 *  3. FAILURE. The endpoint answers 503 when the event table is unmigrated. An error
 *     rendered as an empty raster is the strongest false statement this component can
 *     make, so failure and truncation both render as text, never as blank space.
 */
interface Props {
  litId: string | null;
  onHover: (id: string | null) => void;
  onPick: (leaf: BrainLeaf) => void;
  reloadKey?: number;
}

const WINDOW_DAYS = 30;
/** Ask for the whole window. The endpoint clamps to its own ceiling and tells us via
 * `truncated` + `applied_limit`; asking small and guessing would hide that. */
const LIMIT = 5000;
const MAX_ROWS = 40;

type Row = { ref: string; kind: string; at: number[] };

function groupRows(dto: BrainUsageEventsDto): { rows: Row[]; hidden: number } {
  const by = new Map<string, Row>();
  for (const e of dto.events) {
    const t = e.used_at ? Date.parse(e.used_at) : NaN;
    if (Number.isNaN(t)) continue;
    const row = by.get(e.ref_key) ?? { ref: e.ref_key, kind: e.kind, at: [] };
    row.at.push(t);
    by.set(e.ref_key, row);
  }
  const all = [...by.values()].sort((a, b) => b.at.length - a.at.length);
  return { rows: all.slice(0, MAX_ROWS), hidden: Math.max(0, all.length - MAX_ROWS) };
}

function BrainActivityStrip({ litId, onHover, onPick, reloadKey = 0 }: Props) {
  const [dto, setDto] = useState<BrainUsageEventsDto | null>(null);
  const [failed, setFailed] = useState(false);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    let ok = true;
    const since = new Date(Date.now() - WINDOW_DAYS * 86400_000).toISOString();
    setFailed(false);
    api
      .getBrainUsageEvents({ since, limit: LIMIT })
      .then((d) => ok && setDto(d))
      // 🔴 never fall through to an empty raster — see the header note
      .catch(() => ok && setFailed(true));
    return () => { ok = false; };
  }, [reloadKey]);

  const { rows, hidden } = useMemo(
    () => (dto ? groupRows(dto) : { rows: [], hidden: 0 }),
    [dto],
  );

  const bounds = useMemo(() => {
    const start = dto?.window_start ? Date.parse(dto.window_start) : Date.now() - WINDOW_DAYS * 86400_000;
    return { start, end: Date.now(), span: Math.max(1, Date.now() - start) };
  }, [dto]);

  if (failed) {
    return (
      <div className="brain-strip brain-strip--msg" data-testid="brain-strip">
        <span className="brain-strip__warn">
          活跃时间条暂时不可用(使用事件表可能尚未迁移)。这不代表这些记忆没被用过。
        </span>
      </div>
    );
  }
  if (!dto) return <div className="brain-strip brain-strip--msg" data-testid="brain-strip">…</div>;

  return (
    <div className="brain-strip" data-testid="brain-strip">
      <div className="brain-strip__rows">
        {rows.map((r) => {
          const on = litId === r.ref;
          return (
            <div
              key={r.ref}
              data-strip-row
              data-ref={r.ref}
              className={`brain-strip__row${on ? " is-lit" : ""}`}
              onMouseEnter={() => onHover(r.ref)}
              onMouseLeave={() => onHover(null)}
              onClick={() =>
                onPick({
                  kind: r.kind as BrainLeaf["kind"], ref: r.ref, label: r.ref,
                  provenance: null, confidence: null, usage_count: r.at.length,
                  last_used_at: null, last_used_ref: null, value: 1,
                })
              }
              title={`${r.ref} · ${r.at.length}`}
            >
              {r.at.map((t, i) => (
                <span
                  key={i}
                  className="brain-strip__tick"
                  style={{
                    left: `${((t - bounds.start) / bounds.span) * 100}%`,
                    transition: reduced ? undefined : "opacity 150ms",
                  }}
                />
              ))}
            </div>
          );
        })}
      </div>

      {/* Everything below is the honesty apparatus. It is not decoration: without it an
          empty stretch of the raster reads as "nothing was used then". */}
      <div className="brain-strip__note" data-testid="brain-strip-note">
        {rows.length === 0 && <span>这段时间没有记录到检索。</span>}
        {dto.truncated && (
          <span className="brain-strip__warn">
            已截断:只显示最近 {dto.applied_limit} 次,更早的部分不在图中。
          </span>
        )}
        {hidden > 0 && <span>另有 {hidden} 条记忆未显示(只画最活跃的 {MAX_ROWS} 条)。</span>}
        <span>{dto.coverage_note}</span>
      </div>
    </div>
  );
}

/** The strip can hold thousands of ticks and its parent re-renders on every graph hover.
 * Memoised so sweeping the cursor across the graph does not re-render the whole raster —
 * only `litId` actually changes for it. */
export default memo(BrainActivityStrip);

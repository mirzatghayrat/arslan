import { useEffect, useRef, useState } from "react";
import { ChevronUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RunListItem } from "../api/client.types";
import EvalSummary from "./EvalSummary";
import RunReplay from "./RunReplay";

interface Props {
  /** Backend numeric spawn id to scope runs to. Omit for all runs (orchestrator). */
  spawnId?: number;
}

/**
 * Bottom-of-rail evaluation dock with three progressive-disclosure levels:
 *
 *   1. BAR (collapsed) — a Settings-save-bar-styled bar pinned at the rail bottom.
 *      Shows a label + a mini stat (run count / avg score). Clicking toggles L2.
 *   2. SUMMARY (slides up) — clicking the bar slides a panel UP revealing the
 *      EvalSummary (KPIs + scrollable run list), reusing EvalSummary in inline mode.
 *   3. DETAIL (expands left) — clicking a run opens RunReplay as a panel anchored to
 *      the rail's left edge, growing leftward toward the chat. Back/close → L2.
 */
export default function EvalDock({ spawnId }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);            // L2 summary slide-up
  const [detailRunId, setDetailRunId] = useState<number | null>(null); // L3 expand-left
  const [runs, setRuns] = useState<RunListItem[]>([]);

  // Lightweight stat fetch for the collapsed bar. EvalSummary fetches its own
  // copy when the slide-up mounts; this is just the at-a-glance summary.
  const fetchedFor = useRef<number | string>("__none__");
  useEffect(() => {
    const key = spawnId ?? "__all__";
    if (fetchedFor.current === key) return;
    fetchedFor.current = key;
    let cancelled = false;
    api.getRuns(spawnId)
      .then((r) => { if (!cancelled) setRuns(r); })
      .catch(() => { /* bar stat is best-effort */ });
    return () => { cancelled = true; };
  }, [spawnId]);

  const scored = runs.filter((r) => r.status === "scored" && r.overall_score != null);
  const avg = scored.length
    ? (scored.reduce((s, r) => s + (r.overall_score ?? 0), 0) / scored.length).toFixed(1)
    : null;
  const miniStat = avg != null
    ? `${t('rail.eval_avg')} ${avg}`
    : t('rail.eval_runs', { count: runs.length });

  return (
    <div className="eval-dock">
      {/* L2: summary slide-up (max-height transition) */}
      <div className={`eval-dock__summary${open ? " eval-dock__summary--open" : ""}`}>
        <div className="eval-dock__summary-inner">
          <EvalSummary
            inline
            onClose={() => setOpen(false)}
            spawnId={spawnId}
            onSelectRun={(id) => setDetailRunId(id)}
          />
        </div>
      </div>

      {/* L1: collapsed bar, styled like the Settings save-bar */}
      <button
        type="button"
        className="eval-dock__bar"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="eval-dock__bar-left">
          <span className="eval-dock__bar-label">{t('rail.eval_label')}</span>
          <span className="eval-dock__bar-stat">{miniStat}</span>
        </span>
        <ChevronUp className={`eval-dock__bar-chevron${open ? " eval-dock__bar-chevron--open" : ""}`} />
      </button>

      {/* L3: run detail, expands LEFT from the rail edge toward the chat */}
      {detailRunId != null && (
        <div className="eval-dock__detail-overlay" onClick={() => setDetailRunId(null)}>
          <div className="eval-dock__detail-panel" onClick={(e) => e.stopPropagation()}>
            <RunReplay runId={detailRunId} onClose={() => setDetailRunId(null)} />
          </div>
        </div>
      )}
    </div>
  );
}

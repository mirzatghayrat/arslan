import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { RunSummary } from "../api/client.types";
import { DIMENSION_LABELS } from "../api/adapters";
import type { UiRunDimension } from "../types";
import EChart from "./EChart";

// Same order as the backend judge dimensions.
const DIMENSIONS = ["routing", "fabrication", "identity", "completion"] as const;

interface Props {
  /** This run's per-dimension scores (from UiRun.dimensions). */
  dimensions: UiRunDimension[];
  /** This run's overall score, for the 评分-vs-平均 delta line. */
  overallScore: number | null;
}

/**
 * "本次 vs 整体" — grouped bars comparing this run's per-dimension scores
 * against the fleet averages (GET /runs/summary), plus a subtle 评分 delta
 * line. Self-contained and best-effort: fetch failure or fewer than 2 scored
 * runs renders nothing. Lives at the bottom of RunReplay; the caller should
 * only mount it once the run is scored.
 */
export default function RunCompareChart({ dimensions, overallScore }: Props) {
  const [summary, setSummary] = useState<RunSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getRunsSummary()
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { /* comparison is optional */ });
    return () => { cancelled = true; };
  }, []);

  const scoreByDim = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of dimensions) m[d.dimension] = d.score;
    return m;
  }, [dimensions]);

  const option = useMemo(() => ({
    grid: { left: 28, right: 8, top: 28, bottom: 22 },
    tooltip: {},
    legend: { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 10 } },
    xAxis: {
      type: "category",
      data: DIMENSIONS.map((d) => DIMENSION_LABELS[d] ?? d),
      axisLabel: { fontSize: 10, interval: 0 },
    },
    yAxis: { type: "value", min: 0, max: 10 },
    series: [
      { name: "本次", type: "bar", barWidth: "28%", data: DIMENSIONS.map((d) => scoreByDim[d] ?? null) },
      { name: "平均", type: "bar", barWidth: "28%", data: DIMENSIONS.map((d) => summary?.dimension_averages[d] ?? null) },
    ],
  }), [summary, scoreByDim]);

  // Below 2 scored runs a fleet comparison is noise — render nothing.
  if (summary == null || summary.scored_count < 2) return null;

  const avg = summary.avg_score;
  const delta = avg != null && overallScore != null ? overallScore - avg : null;

  return (
    <section className="run-replay__charts" data-testid="run-compare">
      <h4>本次 vs 整体</h4>
      {delta != null && avg != null && (
        <p className="run-compare__delta">
          评分:平均 {avg.toFixed(1)} · 本次 {delta >= 0 ? "+" : ""}{delta.toFixed(1)}
        </p>
      )}
      <EChart option={option} height={180} />
    </section>
  );
}

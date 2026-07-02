import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { RunSummary } from "../api/client.types";
import { DIMENSION_LABELS } from "../api/adapters";
import EChart from "./EChart";

// Same order as the backend judge dimensions.
const DIMENSIONS = ["routing", "fabrication", "identity", "completion"] as const;

/**
 * Global evaluation charts (score trend / dimension averages / per-spawn pass
 * rate) fed by GET /runs/summary. Self-contained and best-effort: fetch failure
 * or fewer than 2 scored runs renders nothing. Lives in EvalSummary between
 * the KPI row and the run list (global view only — never under a spawn filter).
 */
export default function EvalCharts() {
  const [summary, setSummary] = useState<RunSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getRunsSummary()
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { /* charts are optional */ });
    return () => { cancelled = true; };
  }, []);

  const trendOption = useMemo(() => {
    const pts = (summary?.recent ?? []).filter((p) => p.overall_score != null);
    return {
      grid: { left: 28, right: 12, top: 10, bottom: 20 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: pts.map((p) => `#${p.id}`), axisLabel: { fontSize: 10 } },
      yAxis: { type: "value", min: 0, max: 10 },
      series: [{ type: "line", smooth: true, symbolSize: 5, data: pts.map((p) => p.overall_score) }],
    };
  }, [summary]);

  const dimOption = useMemo(() => ({
    grid: { left: 28, right: 8, top: 10, bottom: 22 },
    tooltip: {},
    xAxis: {
      type: "category",
      data: DIMENSIONS.map((d) => DIMENSION_LABELS[d] ?? d),
      axisLabel: { fontSize: 10, interval: 0 },
    },
    yAxis: { type: "value", min: 0, max: 10 },
    series: [{ type: "bar", barWidth: "55%", data: DIMENSIONS.map((d) => summary?.dimension_averages[d] ?? null) }],
  }), [summary]);

  const spawnOption = useMemo(() => {
    // Top 6 by scored_count; reversed so the most-scored spawn sits on top.
    const top = (summary?.per_spawn ?? []).slice(0, 6).reverse();
    return {
      grid: { left: 64, right: 36, top: 10, bottom: 20 },
      tooltip: {},
      xAxis: { type: "value", min: 0, max: 100, axisLabel: { fontSize: 10 } },
      yAxis: { type: "category", data: top.map((s) => s.spawn_name), axisLabel: { fontSize: 10 } },
      series: [{
        type: "bar", barWidth: "55%",
        data: top.map((s) => s.pass_rate),
        label: { show: true, position: "right", fontSize: 10, formatter: "{c}%" },
      }],
    };
  }, [summary]);

  // Below 2 scored runs the charts are noise — render nothing.
  if (summary == null || summary.scored_count < 2) return null;

  return (
    <section className="run-replay__charts">
      <h4>整体表现</h4>
      <div className="eval-summary__charts" data-testid="eval-charts">
        <div className="eval-chart eval-chart--wide">
          <div className="eval-chart__title">评分趋势</div>
          <EChart option={trendOption} height={170} />
        </div>
        <div className="eval-chart">
          <div className="eval-chart__title">四维平均</div>
          <EChart option={dimOption} height={180} />
        </div>
        <div className="eval-chart">
          <div className="eval-chart__title">分身达标率</div>
          <EChart option={spawnOption} height={180} />
        </div>
      </div>
    </section>
  );
}

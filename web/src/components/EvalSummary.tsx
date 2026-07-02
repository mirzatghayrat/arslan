import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { RunListItem, RunSummary } from "../api/client.types";
import { DIMENSION_LABELS } from "../api/adapters";
import EChart from "./EChart";
import RunReplay from "./RunReplay";

// Same order as the backend judge dimensions.
const DIMENSIONS = ["routing", "fabrication", "identity", "completion"] as const;

interface Props {
  onClose: () => void;
  spawnId?: number;
  /**
   * When `inline` is set, EvalSummary renders bare (no internal full-screen
   * RunReplay swap, no close button) so it can be embedded in the EvalDock
   * slide-up region. Clicking a run is reported via `onSelectRun` instead of
   * opening RunReplay internally. Omitting `inline` keeps the original
   * overlay behaviour intact for any other caller.
   */
  inline?: boolean;
  /** Notified with a run id when a run row is clicked (inline mode). */
  onSelectRun?: (runId: number) => void;
}

export default function EvalSummary({ onClose, spawnId, inline = false, onSelectRun }: Props) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewRunId, setViewRunId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getRuns(spawnId)
      .then((r) => { if (!cancelled) setRuns(r); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [spawnId]);

  // Aggregate charts are global (the endpoint doesn't filter by spawn), so we
  // only fetch/show them in the unfiltered view. Best-effort: failure just
  // means no charts, the run list still works.
  useEffect(() => {
    if (spawnId != null) { setSummary(null); return; }
    let cancelled = false;
    api.getRunsSummary()
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { /* charts are optional */ });
    return () => { cancelled = true; };
  }, [spawnId]);

  // Below 2 scored runs the charts are noise — render nothing extra.
  const showCharts = summary != null && summary.scored_count >= 2;

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

  const handleRowClick = (runId: number) => {
    if (inline) onSelectRun?.(runId);
    else setViewRunId(runId);
  };

  if (!inline && viewRunId != null) {
    return <RunReplay runId={viewRunId} onClose={() => setViewRunId(null)} />;
  }

  const scored = runs.filter((r) => r.status === "scored" && r.overall_score != null);
  const avg = scored.length
    ? (scored.reduce((s, r) => s + (r.overall_score ?? 0), 0) / scored.length).toFixed(1)
    : null;
  const passRate = scored.length
    ? Math.round((scored.filter((r) => (r.overall_score ?? 0) >= 7).length / scored.length) * 100)
    : null;

  return (
    <div className={`eval-summary${inline ? " eval-summary--inline" : ""}`} data-testid="eval-summary">
      {!inline && (
        <header className="eval-summary__head">
          <span className="eval-summary__title">评估摘要</span>
          <button className="eval-summary__close" onClick={onClose} aria-label="close">✕</button>
        </header>
      )}

      {error && <div className="eval-summary__error" role="alert">{error}</div>}

      <div className="eval-summary__kpis">
        <div className="kpi"><div className="kpi__label">已评分</div><div className="kpi__value">{scored.length}</div></div>
        <div className="kpi"><div className="kpi__label">平均分</div><div className="kpi__value">{avg ?? "暂无评分"}</div></div>
        <div className="kpi"><div className="kpi__label">达标率</div><div className="kpi__value">{passRate != null ? `${passRate}%` : "—"}</div></div>
      </div>

      {showCharts && (
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
      )}

      {runs.length === 0 ? (
        <p className="eval-summary__empty">还没有运行记录</p>
      ) : (
        <ul className="eval-list">
          {runs.map((r) => (
            <li key={r.id} className="eval-list__row" onClick={() => handleRowClick(r.id)}>
              <span className="eval-list__spawn">{r.spawn_name ?? "—"}</span>
              <span className={`eval-list__badge eval-list__badge--${r.overall_badge ?? "none"}`}>
                {r.overall_badge ?? ""}
              </span>
              <span className="eval-list__score">
                {r.status === "scored" && r.overall_score != null ? `${r.overall_score}/10` : "评分中"}
              </span>
              <span className="eval-list__ms">{r.total_ms != null ? `${(r.total_ms / 1000).toFixed(1)}s` : ""}</span>
              <span className="eval-list__msg">{r.user_message.slice(0, 40)}{r.user_message.length > 40 ? "…" : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { RunVitalsDto } from "../api/client.types";
import { useThemeStore } from "../stores/themeStore";
import EChart from "./EChart";

interface Props {
  range: "1h" | "24h" | "all";
}

// heatmap ramp low→high. Dark mode: deep-navy base (blends into the dark bg) →
// bright blue. Light mode: pale base (blends into the light bg) → deep blue, so
// empty/low cells read light and busy buckets read dark (light→深).
const HEAT_DARK = ["#0d2a44", "#12507f", "#2a78d6", "#5aa0e8", "#9cc7f2"];
const HEAT_LIGHT = ["#eef4fb", "#c3dcf5", "#7db0e6", "#3a7bd0", "#0d3a63"];

function fmtP95(ms: number | null): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/** Bucketed run-rate + duration heatmap — a compact "vitals" strip above the fleet cards. */
export default function VitalsHeader({ range }: Props) {
  const { t } = useTranslation();
  const [vitals, setVitals] = useState<RunVitalsDto | null>(null);
  const mode = useThemeStore((s) => s.mode);

  useEffect(() => {
    let cancelled = false;
    api.getRunVitals(range)
      .then((v) => { if (!cancelled) setVitals(v); })
      .catch(() => { /* best-effort */ });
    return () => { cancelled = true; };
  }, [range]);

  if (!vitals) return null;

  if (vitals.total === 0) {
    return (
      <div className="vitals" data-testid="vitals-header">
        <div className="vitals__empty">{t("diag.vitals_empty")}</div>
      </div>
    );
  }

  let max = 0;
  const heatData: [number, number, number][] = [];
  vitals.duration_matrix.forEach((row, bi) => {
    row.forEach((count, ti) => {
      heatData.push([ti, bi, count]);
      if (count > max) max = count;
    });
  });

  const heatOption = {
    backgroundColor: "transparent",
    grid: { left: 60, right: 12, top: 8, bottom: 36, containLabel: false },
    xAxis: {
      type: "category",
      data: Array.from({ length: 30 }, (_, i) => String(i)),
      axisLabel: { show: false },
      axisTick: { show: false },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: vitals.duration_bins,
      axisLabel: { fontSize: 10 },
      splitArea: { show: false },
    },
    visualMap: {
      min: 0,
      max: max || 1,
      calculable: false,
      orient: "horizontal",
      bottom: 0,
      inRange: { color: mode === "light" ? HEAT_LIGHT : HEAT_DARK },
    },
    tooltip: {
      formatter: (p: { data: [number, number, number] }) =>
        `${vitals.duration_bins[p.data[1]]}: ${t("diag.times_n", { n: p.data[2] })}`,
    },
    series: [
      {
        type: "heatmap",
        data: heatData,
        emphasis: { itemStyle: { shadowBlur: 6 } },
      },
    ],
  };

  return (
    <div className="vitals" data-testid="vitals-header">
      <div className="vitals__hero">
        <div className="vitals__hero-item">
          <div className="vitals__hero-num">{vitals.total}</div>
          <div className="vitals__hero-label">{t("diag.runs")}</div>
        </div>
        <div className="vitals__hero-item">
          <div className="vitals__hero-num">{(vitals.error_ratio * 100).toFixed(1)}%</div>
          <div className="vitals__hero-label">{t("diag.error_rate")}</div>
        </div>
        <div className="vitals__hero-item">
          <div className="vitals__hero-num">{fmtP95(vitals.p95_ms)}</div>
          <div className="vitals__hero-label">P95</div>
        </div>
      </div>
      <EChart option={heatOption} height={140} />
    </div>
  );
}

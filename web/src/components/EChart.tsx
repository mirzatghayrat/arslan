// web/src/components/EChart.tsx
//
// Renders a backend-built ECharts option object (artifact { kind: "echarts",
// spec }) inside the chat. The spec is plain JSON (no functions) — we pass it
// straight to chart.setOption(spec).
//
// 🔒 SECURITY: the `option` here originates ONLY from a backend render_chart
// tool_result artifact (carried through arslanStore → toolSteps →
// toolActivity.artifactChart). It is NEVER derived from LLM message text.
//
// Theme: colors/fonts/background come from the live Arslan palette (semantic
// CSS vars on :root), so the chart looks correct in every theme (dark+amber and
// the alternate palettes). We register the theme lazily on first render and
// re-read the vars then, because module-load-time getComputedStyle can run
// before the theme stylesheet is applied.
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

const THEME_NAME = "arslan";
let themeRegistered = false;

function cssVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  const v = styles.getPropertyValue(name).trim();
  return v || fallback;
}

/** Build the echarts theme from the current semantic CSS vars. */
function buildArslanTheme(): Record<string, unknown> {
  const styles = getComputedStyle(document.documentElement);

  const primary = cssVar(styles, "--color-primary", "#FF8E24");
  const foreground = cssVar(styles, "--color-foreground", "#FFFFFF");
  const muted = cssVar(styles, "--color-muted-foreground", "#94A3B8");
  const border = cssVar(styles, "--color-border", "#1E2330");
  const surface = cssVar(styles, "--color-surface", "#121622");
  const success = cssVar(styles, "--color-success", "#10B981");
  const info = cssVar(styles, "--color-info", "#3B82F6");
  const warning = cssVar(styles, "--color-warning", "#F59E0B");
  const danger = cssVar(styles, "--color-danger", "#EF4444");
  const subtle = cssVar(styles, "--color-subtle-foreground", muted);

  // Palette seeded from the primary accent, then complementary hues. Used for
  // multi-series charts (bar/line/pie/radar/funnel/...).
  const palette = [primary, info, success, warning, danger, "#A78BFA", "#22D3EE", subtle];

  const axisLine = { lineStyle: { color: border } };
  const axisLabel = { color: muted };
  const splitLine = { lineStyle: { color: border, type: "dashed" as const } };

  return {
    color: palette,
    backgroundColor: "transparent",
    textStyle: { color: foreground },
    title: {
      textStyle: { color: foreground },
      subtextStyle: { color: muted },
    },
    legend: { textStyle: { color: muted } },
    tooltip: {
      backgroundColor: surface,
      borderColor: border,
      textStyle: { color: foreground },
    },
    categoryAxis: { axisLine, axisTick: axisLine, axisLabel, splitLine: { ...splitLine, show: false } },
    valueAxis: { axisLine, axisTick: axisLine, axisLabel, splitLine },
    logAxis: { axisLine, axisTick: axisLine, axisLabel, splitLine },
    timeAxis: { axisLine, axisTick: axisLine, axisLabel, splitLine },
    radar: {
      axisLine: { lineStyle: { color: border } },
      splitLine: { lineStyle: { color: border } },
      axisName: { color: muted },
      splitArea: { areaStyle: { color: ["transparent"] } },
    },
    gauge: {
      axisLine: { lineStyle: { color: [[1, border]] } },
      axisLabel: { color: muted },
      title: { color: foreground },
      detail: { color: primary },
    },
  };
}

function ensureThemeRegistered(): void {
  if (themeRegistered) return;
  echarts.registerTheme(THEME_NAME, buildArslanTheme());
  themeRegistered = true;
}

interface EChartProps {
  option: Record<string, unknown>;
  className?: string;
  /** Chart height in px (default 320 = in-chat artifact size). */
  height?: number;
}

export default function EChart({ option, className, height = 320 }: EChartProps) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  // Init / dispose lifecycle.
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;

    ensureThemeRegistered();
    // SVG renderer: the DOM holds a real <svg> (captured by the per-message
    // .html export in MessageBody), and charts stay crisp/static.
    const chart = echarts.init(el, THEME_NAME, { renderer: "svg" });
    chartRef.current = chart;

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply / update the option whenever it changes.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setOption(option, true);
  }, [option]);

  return (
    <div
      ref={elRef}
      className={className}
      style={{ width: "100%", height }}
      data-testid="echart"
    />
  );
}

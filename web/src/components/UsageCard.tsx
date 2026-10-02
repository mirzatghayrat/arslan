import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { UsageBin, UsageSummary } from "../api/client.types";
import { fmtMs, fmtTok, fmtUsd } from "../lib/usageFormat";

type RangeKey = "24h" | "7d" | "30d";
const RANGES: RangeKey[] = ["24h", "7d", "30d"];

/** A palette-aware tint of the accent: every theme and palette gets its own heat scale. */
const tint = (pct: number) => `color-mix(in srgb, var(--primary) ${Math.round(pct)}%, transparent)`;

/**
 * Activity › Usage (0.1.50): what the work did and what it cost, at a glance.
 *
 * Five numbers (runs, success, p95 time, tokens, cost), then three rows that
 * share one time axis — tokens per slice, how long finished work took (a
 * heatmap of duration bands), and how each slice ended — then the per-model
 * breakdown. All from GET /usage/summary; an older backend without the run
 * series still shows the numbers it has and the model list.
 *
 * Honesty rules mirrored from the backend: ≈ marks figures that include
 * estimates; unknown cost renders "—", never $0 (unknown ≠ free).
 */
export default function UsageCard() {
  const { t, i18n } = useTranslation();
  const [range, setRange] = useState<RangeKey>("7d");
  const [summary, setSummary] = useState<UsageSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getUsageSummary(range)
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { /* dashboard is best-effort */ });
    return () => { cancelled = true; };
  }, [range]);

  const rows = summary?.rows ?? [];
  // A model line with no tokens says nothing; the totals above still count everything.
  const modelRows = rows.filter((r) => r.tokens_total > 0);
  const bins = summary?.bins ?? [];
  const runs = summary?.runs;
  const tokens = summary?.tokens_total ?? rows.reduce((n, r) => n + r.tokens_total, 0);
  const estimated = summary?.estimated_any ?? rows.some((r) => r.estimated_any);
  const priced = rows.filter((r) => r.usd != null);
  const usd = summary?.usd_total !== undefined ? summary.usd_total
    : priced.length ? priced.reduce((n, r) => n + (r.usd ?? 0), 0) : null;
  const finished = runs ? runs.done + runs.failed : 0;
  const maxRowTokens = Math.max(1, ...modelRows.map((r) => r.tokens_total));

  return (
    <section className="space-y-3" data-testid="usage-card">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-foreground">{t("usage.title")}</h2>
        <div className="diag-catalog__range" role="tablist" aria-label={t("ui.range")}>
          {RANGES.map((r) => (
            <button key={r} type="button" role="tab" aria-selected={range === r} data-testid={`usage-range-${r}`}
              className={`diag-catalog__range-btn${range === r ? " diag-catalog__range-btn--active" : ""}`}
              onClick={() => setRange(r)}>
              {t(`usage.range.${r}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5" data-testid="usage-kpis">
        <Kpi label={t("activityPage.kpiRuns")} value={runs ? String(runs.total) : "—"}
          sub={runs ? (runs.running ? t("activityPage.runningN", { n: runs.running })
            : t("activityPage.failedN", { n: runs.failed })) : undefined}
          subTone={runs && runs.failed > 0 && !runs.running ? "danger" : undefined} />
        <Kpi label={t("activityPage.kpiSuccess")}
          value={finished ? `${Math.round((runs!.done / finished) * 100)}%` : "—"}
          sub={finished ? t("activityPage.ofN", { done: runs!.done, n: finished }) : undefined}
          tone={finished && runs!.failed / finished > 0.2 ? "danger" : undefined}
          subTone={finished ? "success" : undefined} />
        <Kpi label={t("activityPage.kpiP95")} value={runs?.p95_ms != null ? fmtMs(runs.p95_ms) : "—"}
          sub={runs?.p50_ms != null ? t("activityPage.median", { v: fmtMs(runs.p50_ms) }) : undefined} />
        <Kpi label={t("activityPage.kpiTokens")} value={`${estimated && tokens ? "≈ " : ""}${fmtTok(tokens)}`}
          sub={rows.length ? t("activityPage.modelsN", { n: new Set(rows.map((r) => r.model)).size }) : undefined} />
        <Kpi label={t("activityPage.kpiCost")} value={usd != null ? fmtUsd(usd) : "—"}
          sub={rows.length && priced.length < rows.length ? t("activityPage.partlyPriced") : undefined} />
      </div>

      {bins.length > 0 && (summary?.duration_bands?.length ?? 0) > 0 ? (
        <Timeline bins={bins} bands={summary!.duration_bands!} binSeconds={summary!.bin_seconds ?? 3600}
          range={range} locale={i18n.language} />
      ) : (summary?.daily.length ?? 0) > 0 && (
        // An older backend sends only daily totals: still draw them.
        <div className="flex h-12 items-end gap-[3px] rounded-lg border border-border bg-surface/40 p-3" data-testid="usage-daily-spark">
          {summary!.daily.map((d) => {
            const max = Math.max(1, ...summary!.daily.map((x) => x.tokens_total));
            return <span key={d.date} title={`${d.date} · ${fmtTok(d.tokens_total)}`} className="block flex-1 rounded-sm"
              style={{ height: `${Math.max(8, (d.tokens_total / max) * 100)}%`, background: tint(85) }} />;
          })}
        </div>
      )}

      {modelRows.length === 0 ? (
        <p className="text-xs text-subtle-foreground">{t("usage.empty")}</p>
      ) : (
        <div className="rounded-lg border border-border bg-surface/40 p-3">
          <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{t("activityPage.byModel")}</h3>
          <ul className="space-y-1.5">
            {modelRows.map((r, i) => (
              <li key={i} data-testid="usage-row" className="grid grid-cols-[minmax(0,1fr)_minmax(60px,30%)_auto_auto] items-center gap-3 text-[12px]">
                <span className="min-w-0 truncate">
                  <span className="font-mono text-foreground">{r.model ?? "—"}</span>
                  <span className="ml-2 text-subtle-foreground">{r.provider ?? "—"} · {r.scope}</span>
                </span>
                <span className="h-1.5 overflow-hidden rounded-full bg-border/60" aria-hidden>
                  <span className="block h-full rounded-full" style={{ width: `${Math.max(2, (r.tokens_total / maxRowTokens) * 100)}%`, background: tint(80) }} />
                </span>
                <span className="w-16 text-right font-mono tabular-nums text-foreground">{r.estimated_any ? "≈ " : ""}{fmtTok(r.tokens_total)}</span>
                <span className="w-14 text-right font-mono tabular-nums text-muted-foreground">{r.usd != null ? fmtUsd(r.usd) : "—"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary != null && summary.not_covered.length > 0 && (
        <details className="usage-card__notcovered" data-testid="usage-notcovered">
          <summary>{t("usage.notCovered")} · {summary.not_covered.length}</summary>
          <div className="usage-card__notcovered-list">{summary.not_covered.join(" · ")}</div>
        </details>
      )}
    </section>
  );
}

type Tone = "danger" | "success";
const toneText = (tone: Tone | undefined, fallback: string) =>
  tone === "danger" ? "text-danger" : tone === "success" ? "text-success" : fallback;

function Kpi({ label, value, sub, tone, subTone }: { label: string; value: string; sub?: string; tone?: Tone; subTone?: Tone }) {
  return (
    <div className="rounded-lg border border-border bg-surface/60 px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-lg font-semibold tabular-nums ${toneText(tone, "text-foreground")}`}>{value}</div>
      {sub && <div className={`mt-0.5 truncate text-[11px] ${toneText(subTone, "text-subtle-foreground")}`}>{sub}</div>}
    </div>
  );
}

/** Three rows on one time axis: tokens, duration heatmap, outcome. */
function Timeline({ bins, bands, binSeconds, range, locale }:
  { bins: UsageBin[]; bands: string[]; binSeconds: number; range: RangeKey; locale: string }) {
  const { t } = useTranslation();
  const fmt = useMemo(() => new Intl.DateTimeFormat(locale, range === "24h"
    ? { hour: "2-digit", minute: "2-digit" } : range === "7d"
      ? { weekday: "short", hour: "2-digit" } : { month: "short", day: "numeric" }), [locale, range]);
  const span = (b: UsageBin) => `${fmt.format(new Date(b.start_ts * 1000))} – ${fmt.format(new Date((b.start_ts + binSeconds) * 1000))}`;
  const maxTokens = Math.max(1, ...bins.map((b) => b.tokens_total));
  const maxCell = Math.max(1, ...bins.flatMap((b) => b.durations));
  const cols = { gridTemplateColumns: `repeat(${bins.length}, minmax(0, 1fr))` };
  const label = "w-16 shrink-0 pr-2 text-right text-[10px] text-subtle-foreground";

  return (
    <div className="rounded-lg border border-border bg-surface/40 p-3" data-testid="usage-timeline">
      {/* Tokens per slice (the daily spark's successor). */}
      <div className="flex items-end" data-testid="usage-daily-spark">
        <span className={`${label} self-center`}>{t("activityPage.chartTokens")}</span>
        <div className="grid h-12 flex-1 items-end gap-[3px]" style={cols}>
          {bins.map((b) => (
            <span key={b.start_ts} title={`${span(b)} · ${fmtTok(b.tokens_total)}`}
              className="block w-full rounded-sm" style={{
                height: b.tokens_total ? `${Math.max(8, (b.tokens_total / maxTokens) * 100)}%` : "2px",
                background: b.tokens_total ? tint(85) : "var(--border)" }} />
          ))}
        </div>
      </div>

      {/* How long finished work took: longest band on top, like a latency heatmap. */}
      <div className="mt-3 space-y-[3px]" data-testid="usage-heatmap">
        {bands.map((band, i) => ({ band, i })).reverse().map(({ band, i }) => (
          <div key={band} className="flex items-center">
            <span className={label}>{band}</span>
            <div className="grid flex-1 gap-[3px]" style={cols}>
              {bins.map((b) => {
                const n = b.durations[i] ?? 0;
                return <span key={b.start_ts} title={`${span(b)} · ${band} · ${n}`}
                  className="block h-3.5 rounded-[3px]"
                  style={{ background: n ? tint(25 + (n / maxCell) * 75) : "color-mix(in srgb, var(--border) 55%, transparent)" }} />;
              })}
            </div>
          </div>
        ))}
      </div>

      {/* How each slice ended. */}
      <div className="mt-3 flex items-center" data-testid="usage-outcomes">
        <span className={label}>{t("activityPage.chartOutcome")}</span>
        <div className="grid flex-1 gap-[3px]" style={cols}>
          {bins.map((b) => (
            <span key={b.start_ts}
              title={`${span(b)} · ${t("activityPage.sliceRuns", { n: b.runs, failed: b.failed })}`}
              className={`block h-3.5 rounded-[3px] ${b.failed ? "bg-danger" : b.runs ? "bg-success" : ""}`}
              style={b.runs ? undefined : { background: "color-mix(in srgb, var(--border) 55%, transparent)" }} />
          ))}
        </div>
      </div>

      <div className="mt-2 flex pl-16 font-mono text-[10px] text-subtle-foreground">
        <span className="flex-1">{fmt.format(new Date(bins[0].start_ts * 1000))}</span>
        <span className="flex-1 text-center">{fmt.format(new Date(bins[Math.floor(bins.length / 2)].start_ts * 1000))}</span>
        <span className="flex-1 text-right">{t("activityPage.now")}</span>
      </div>
      <div className="mt-2 flex items-center justify-end gap-2 text-[10px] text-subtle-foreground">
        <span>{t("activityPage.chartTime")}</span>
        <span className="flex gap-[2px]" aria-hidden>
          {[25, 45, 65, 85, 100].map((p) => <span key={p} className="h-2 w-3 rounded-[2px]" style={{ background: tint(p) }} />)}
        </span>
        <span>{t("activityPage.more")}</span>
      </div>
    </div>
  );
}

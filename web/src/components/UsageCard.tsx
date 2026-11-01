import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { api } from "../api/client";
import type { UsageBin, UsageSummary, UsageSummaryRow } from "../api/client.types";
import type { WaitingView } from "../hooks/useWaiting";
import { fmtMs, fmtTok, fmtUsd } from "../lib/usageFormat";
import { useActivityStore, type UsageRange } from "../stores/activityStore";
import { AxisHead, RunsLane, StepLane, useAxisRuns, useFreshRead } from "./activity/RunsLane";

type RangeKey = UsageRange;
const RANGES: RangeKey[] = ["24h", "7d", "30d"];

/** A palette-aware tint of the accent: every theme and palette gets its own heat scale. */
const tint = (pct: number) => `color-mix(in srgb, var(--primary) ${Math.round(pct)}%, transparent)`;

/** INB7-a: the chart palette (tokens.css --series-1..3). Three slots that stay apart for colour-blind readers in any order, so a
 *  model can keep its slot whatever its rank; a fourth model and beyond fold into Other, in grey. */
const SLOTS = 3;
// #610 review F5: --muted-foreground, 3:1 or more on the light surface in every palette (--subtle-foreground was 2.5–2.7).
const OTHER = "var(--muted-foreground)";
const slotColour = (slot: number) => `var(--series-${slot + 1})`;

/** Each of the largest models keeps the slot it had, so a range change does not repaint a model the reader has learned; a model
 *  new to the bar takes the first free slot. `models` is at most SLOTS long, largest first. */
export function assignSlots(models: string[], remembered: Record<string, number>): Record<string, number> {
  const slots: Record<string, number> = {};
  const taken = new Set<number>();
  for (const model of models) {
    const slot = remembered[model];
    if (slot !== undefined && slot < SLOTS && !taken.has(slot)) { slots[model] = slot; taken.add(slot); }
  }
  for (const model of models) {
    if (slots[model] !== undefined) continue;
    const free = [0, 1, 2].find((slot) => !taken.has(slot))!;
    slots[model] = free;
    taken.add(free);
  }
  return slots;
}

/** The priced cost by model, largest first: the three largest in their slots, the rest (and priced calls with no model) as Other.
 *  A call with no price is left out, because unknown is not free; a call that cost nothing is priced but has nothing to draw. */
function costByModel(rows: UsageSummaryRow[], remembered: Record<string, number>) {
  const byModel = new Map<string, number>();
  const costsNothing = new Set<string>();
  let unnamed = 0;
  for (const r of rows) {
    if (r.usd == null) continue;
    if (r.usd === 0) { if (r.model) costsNothing.add(r.model); continue; }
    if (r.model) byModel.set(r.model, (byModel.get(r.model) ?? 0) + r.usd); else unnamed += r.usd;
  }
  const ranked = [...byModel].sort((a, b) => b[1] - a[1]);
  const slots = assignSlots(ranked.slice(0, SLOTS).map(([model]) => model), remembered);
  const other = ranked.slice(SLOTS).reduce((n, [, usd]) => n + usd, unnamed);
  const segments: { key: string; model?: string; usd: number; colour: string }[] = ranked.slice(0, SLOTS)
    .map(([model, usd]) => ({ key: model, model, usd, colour: slotColour(slots[model]) }));
  if (other > 0) segments.push({ key: "other", usd: other, colour: OTHER });
  const colourOf = (model: string | null) => model === null ? (unnamed > 0 ? OTHER : undefined)
    : slots[model] !== undefined ? slotColour(slots[model]) : byModel.has(model) ? OTHER : undefined;
  // #610 review F2: a model that only cost nothing is priced, so its key is hollow (nothing in the bar), not missing as for no price.
  const free = (model: string | null) => model !== null && costsNothing.has(model) && !byModel.has(model);
  return { segments, slots, colourOf, free, total: segments.reduce((n, s) => n + s.usd, 0) };
}

/**
 * Progress › Usage (0.1.50, the page was Activity until v0.1.64): what the work did and what it cost, at a glance.
 *
 * The top row (INB7-a, board F): what waits on you, the four work numbers (runs, success, p95 time, tokens), and the cost, whose
 * bar splits it by model and which opens the by-model table in place. Then three rows that share one time axis — tokens per
 * slice, how long finished work took (a heatmap of duration bands), and how each slice ended. All from GET /usage/summary; an
 * older backend without the run series still shows the numbers it has and the model list.
 *
 * Honesty rules mirrored from the backend: ≈ marks figures that include
 * estimates; unknown cost renders "—", never $0 (unknown ≠ free).
 */
export default function UsageCard({ waiting }: { waiting?: WaitingView }) {
  const { t, i18n } = useTranslation();
  // 0.1.58: the range lives in the Activity store, so leaving the page keeps it; so does an open cost by model (INB7-a).
  const range = useActivityStore((s) => s.range);
  const setRange = useActivityStore((s) => s.setRange);
  const filter = useActivityStore((s) => s.filter);
  const setFilter = useActivityStore((s) => s.setFilter);
  const byModelOpen = useActivityStore((s) => s.byModelOpen);
  const setByModelOpen = useActivityStore((s) => s.setByModelOpen);
  const remembered = useActivityStore((s) => s.modelSlots);
  const rememberSlots = useActivityStore((s) => s.rememberSlots);
  const [summary, setSummary] = useState<UsageSummary | null>(null);

  // Over a day the summary is read on the axis's beat too, so the axis's window keeps up with now and a running bar keeps growing
  // (INB7-b; ⓪Plan's re-check of PR 622, A). Over 7 and 30 days, a heavier read, it is read once per range, as before.
  const day = range === "24h";
  const readSummary = useCallback(() => api.getUsageSummary(range), [range]);
  useFreshRead(day ? readSummary : null, setSummary);
  useEffect(() => {
    if (day) return;
    let cancelled = false;
    readSummary()
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { /* dashboard is best-effort */ });
    return () => { cancelled = true; };
  }, [day, readSummary]);

  const cost = useMemo(() => costByModel(summary?.rows ?? [], remembered), [summary, remembered]);
  useEffect(() => { rememberSlots(cost.slots); }, [cost.slots, rememberSlots]);

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
  const pickModel = (model: string) => setFilter({ ...filter, model: filter.model === model ? undefined : model });

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

      <div className={`grid grid-cols-2 gap-2 sm:grid-cols-3 ${waiting ? "xl:grid-cols-6" : "xl:grid-cols-5"}`} data-testid="usage-kpis">
        {waiting && <NeedsTile waiting={waiting} />}
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
        {/* INB7-a: the cost tile opens the cost by model in place; its bar is the same split, largest first. */}
        <button type="button" data-testid="usage-cost" aria-expanded={byModelOpen} aria-controls="usage-by-model"
          aria-label={t("activityPage.costTileLabel", { cost: usd != null ? fmtUsd(usd) : "—" })}
          aria-describedby={rows.length > 0 && priced.length < rows.length ? "usage-cost-note" : undefined}
          onClick={() => setByModelOpen(!byModelOpen)}
          className={`rounded-lg border bg-surface/60 px-3 py-2.5 text-left outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-primary/50 ${
            byModelOpen ? "border-foreground/40" : "border-border"}`}>
          <span className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            <span>{t("activityPage.kpiCost")}</span>
            <span className="ml-auto flex items-center gap-0.5 normal-case tracking-normal">
              {t("activityPage.byModel")}
              <ChevronDown size={12} aria-hidden className={byModelOpen ? "rotate-180" : undefined} />
            </span>
          </span>
          <span className="mt-1 block font-mono text-lg font-semibold tabular-nums text-foreground">{usd != null ? fmtUsd(usd) : "—"}</span>
          {cost.segments.length > 0 && (
            <span className="mt-1.5 flex h-1.5 gap-[2px]" data-testid="usage-cost-bar">
              {cost.segments.map((s, i) => {
                const label = s.model ?? t("activityPage.otherModels");
                return <span key={s.key} data-testid="usage-cost-seg" title={`${label} · ${fmtUsd(s.usd)} · ${Math.round((s.usd / cost.total) * 100)}%`}
                  className={`block h-full min-w-[3px] ${i === 0 ? "rounded-l-full" : ""} ${i === cost.segments.length - 1 ? "rounded-r-full" : ""}`}
                  style={{ flexGrow: (s.usd / cost.total) * 100, flexBasis: 0, background: s.colour }} />;
              })}
            </span>
          )}
          {rows.length > 0 && priced.length < rows.length && (
            <span id="usage-cost-note" className="mt-0.5 block truncate text-[11px] text-subtle-foreground">{t("activityPage.partlyPriced")}</span>
          )}
        </button>
      </div>

      {byModelOpen && (
        <div id="usage-by-model" data-testid="usage-by-model" className="rounded-lg border border-border bg-surface/40 p-3">
          {modelRows.length === 0 ? (
            <p className="text-xs text-subtle-foreground">{t("usage.empty")}</p>
          ) : (
            <ul className="space-y-1.5">
              {modelRows.map((r, i) => {
                const colour = cost.colourOf(r.model);
                return (
                  <li key={i} data-testid="usage-row" role={r.model ? "button" : undefined} tabIndex={r.model ? 0 : undefined}
                    aria-pressed={r.model ? filter.model === r.model : undefined}
                    title={r.model ? t("activityPage.filterModel") : undefined}
                    onClick={() => r.model && pickModel(r.model)}
                    onKeyDown={(e) => { if (r.model && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pickModel(r.model); } }}
                    className={`grid grid-cols-[minmax(0,1fr)_minmax(60px,30%)_auto_auto] items-center gap-3 rounded px-1 text-[12px] ${r.model ? "cursor-pointer hover:bg-surface/70" : ""} ${filter.model && filter.model === r.model ? "bg-primary/10" : ""}`}>
                    <span className="min-w-0 truncate">
                      {/* The key to the bar: a model with no price is not in it, so it gets an empty space, not a colour. */}
                      {colour ? <span data-testid="usage-swatch" aria-hidden className="mr-2 inline-block h-2 w-2 rounded-[2px] align-middle" style={{ background: colour }} />
                        : cost.free(r.model) ? <span data-testid="usage-swatch" data-free aria-hidden
                            className="mr-2 inline-block h-2 w-2 rounded-[2px] border border-muted-foreground align-middle" />
                        : <span aria-hidden className="mr-2 inline-block h-2 w-2 align-middle" />}
                      <span className="font-mono text-foreground">{r.model ?? "—"}</span>
                      <span className="ml-2 text-subtle-foreground">{r.provider ?? "—"} · {r.scope}</span>
                    </span>
                    <span className="h-1.5 overflow-hidden rounded-full bg-border/60" aria-hidden>
                      <span className="block h-full rounded-full" style={{ width: `${Math.max(2, (r.tokens_total / maxRowTokens) * 100)}%`, background: colour ?? "var(--border-strong)" }} />
                    </span>
                    <span className="w-16 text-right font-mono tabular-nums text-foreground">{r.estimated_any ? "≈ " : ""}{fmtTok(r.tokens_total)}</span>
                    <span className="w-14 text-right font-mono tabular-nums text-muted-foreground">{r.usd != null ? fmtUsd(r.usd) : "—"}</span>
                  </li>
                );
              })}
            </ul>
          )}
          {summary != null && summary.not_covered.length > 0 && (
            <details className="usage-card__notcovered mt-2" data-testid="usage-notcovered">
              <summary>{t("usage.notCovered")} · {summary.not_covered.length}</summary>
              <div className="usage-card__notcovered-list">{summary.not_covered.join(" · ")}</div>
            </details>
          )}
        </div>
      )}

      {bins.length > 0 && (summary?.duration_bands?.length ?? 0) > 0 ? (
        <Timeline bins={bins} bands={summary!.duration_bands!} binSeconds={summary!.bin_seconds ?? 3600}
          range={range} locale={i18n.language}
          selected={filter.since}
          onPick={(b) => setFilter({ ...filter, since: b.start_ts, until: b.start_ts + (summary!.bin_seconds ?? 3600) })} />
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
    </section>
  );
}

/** INB7-a: what waits on you leads the row (the count the badge on Progress shows), with what it is: conversations, projects and
 *  scheduled tasks. Until the server has answered it says —, never "all caught up". INB7-c makes it the list's filter. */
function NeedsTile({ waiting }: { waiting: WaitingView }) {
  const { t } = useTranslation();
  const asking = waiting.loaded && waiting.count > 0;
  const parts = [
    waiting.conversations.length ? t("activityPage.needsConversations", { count: waiting.conversations.length }) : "",
    waiting.projects.length ? t("activityPage.needsProjects", { count: waiting.projects.length }) : "",
    waiting.scheduled.length ? t("activityPage.needsTasks", { count: waiting.scheduled.length }) : "",
  ].filter(Boolean);
  return (
    <div data-testid="usage-needs" className={`rounded-lg border px-3 py-2.5 ${asking ? "border-warning/40 bg-ask-soft" : "border-border bg-surface/60"}`}>
      <div className={`text-[10px] font-medium uppercase tracking-wide ${asking ? "text-warning" : "text-muted-foreground"}`}>{t("activityPage.kpiNeeds")}</div>
      <div className={`mt-1 font-mono text-lg font-semibold tabular-nums ${asking ? "text-warning" : "text-foreground"}`}>
        {waiting.loaded ? String(waiting.count) : "—"}</div>
      {waiting.loaded && <div className={`mt-0.5 truncate text-[11px] ${asking ? "text-muted-foreground" : "text-success"}`}>
        {asking ? parts.join(" · ") : t("activityPage.needsNone")}</div>}
    </div>
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

/** Rows on one time axis: tokens, then over 7 and 30 days the duration heatmap and outcome; over 24 hours (INB7-b, board F) one bar
 *  per run instead, and the picked run's steps with their replay. The user: 「热力图只在 7 天和 30 天显示」. */
function Timeline({ bins, bands, binSeconds, range, locale, selected, onPick }:
  { bins: UsageBin[]; bands: string[]; binSeconds: number; range: RangeKey; locale: string;
    selected?: number; onPick?: (b: UsageBin) => void }) {
  const { t } = useTranslation();
  const [hover, setHover] = useState<number | null>(null);
  const day = range === "24h";
  const t0 = bins[0].start_ts * 1000;
  const t1 = (bins[bins.length - 1].start_ts + binSeconds) * 1000;
  const { runs, now } = useAxisRuns(t0, day);
  const pickedRunId = useActivityStore((s) => s.pickedRunId);
  const fmt = useMemo(() => new Intl.DateTimeFormat(locale, range === "24h"
    ? { hour: "2-digit", minute: "2-digit" } : range === "7d"
      ? { weekday: "short", hour: "2-digit" } : { month: "short", day: "numeric" }), [locale, range]);
  const span = (b: UsageBin) => `${fmt.format(new Date(b.start_ts * 1000))} – ${fmt.format(new Date((b.start_ts + binSeconds) * 1000))}`;
  const maxTokens = Math.max(1, ...bins.map((b) => b.tokens_total));
  const maxCell = Math.max(1, ...bins.flatMap((b) => b.durations));
  const cols = { gridTemplateColumns: `repeat(${bins.length}, minmax(0, 1fr))` };
  const label = "w-16 shrink-0 pr-2 text-right text-[10px] text-subtle-foreground";

  const hb = hover != null ? bins[hover] : null;
  return (
    <div className="relative rounded-lg border border-border bg-surface/40 p-3" data-testid="usage-timeline"
      onMouseLeave={() => setHover(null)}>
      {day && <AxisHead runs={runs} picked={pickedRunId != null} />}
      <div className="relative">
        {/* 0.1.58 §7: one hit area per column across the slice rows — hover shows one card for
            the slice, a click narrows 最近的工作 to it. Keyboard: Tab to a column, Enter. The runs
            lane (24 hours) sits below, outside them, so each bar takes its own click. */}
        <div className="absolute inset-y-0 left-16 right-0 z-10 grid gap-[3px]" style={cols} data-testid="usage-columns">
          {bins.map((b, i) => (
            <button key={b.start_ts} type="button" data-testid={`usage-col-${i}`}
              aria-label={`${span(b)} · ${t("activityPage.sliceRuns", { n: b.runs, failed: b.failed })}`}
              aria-pressed={selected === b.start_ts}
              onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
              onClick={() => onPick?.(b)}
              className={`rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                selected === b.start_ts ? "bg-primary/15" : hover === i ? "bg-foreground/5" : ""}`} />
          ))}
        </div>
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
        {!day && (
          <>
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
          </>
        )}
      </div>
      {hb && (
        <div role="tooltip" data-testid="usage-hovercard"
          className="pointer-events-none absolute top-2 z-20 w-60 rounded-lg bg-foreground px-3 py-2 text-[11.5px] leading-relaxed text-background shadow-lg"
          style={hover! / bins.length > 0.5
            ? { right: `calc(${(1 - (hover! + 1) / bins.length) * 100}% + 12px)` }
            : { left: `calc(${((hover! + 1) / bins.length) * 100}% + 12px)` }}>
          <div className="font-semibold">{span(hb)}</div>
          <div>{t("activityPage.sliceRuns", { n: hb.runs, failed: hb.failed })} · {fmtTok(hb.tokens_total)}</div>
          {hb.p50_ms != null && <div>{t("activityPage.hoverTimes", { p50: fmtMs(hb.p50_ms), max: fmtMs(hb.max_ms ?? hb.p50_ms) })}</div>}
          {hb.usd != null && <div>≈ {fmtUsd(hb.usd)}</div>}
          {!!hb.models?.length && <div className="opacity-70">{hb.models.map((m) => m.model).join(" · ")}</div>}
          {onPick && hb.runs > 0 && <div className="mt-0.5 text-primary">{t("activityPage.clickToFilter")}</div>}
        </div>
      )}
      {day && <RunsLane runs={runs} now={now} t0={t0} t1={t1} locale={locale} />}

      <div className="mt-2 flex pl-16 font-mono text-[10px] text-subtle-foreground">
        <span className="flex-1">{fmt.format(new Date(bins[0].start_ts * 1000))}</span>
        <span className="flex-1 text-center">{fmt.format(new Date(bins[Math.floor(bins.length / 2)].start_ts * 1000))}</span>
        <span className="flex-1 text-right">{t("activityPage.now")}</span>
      </div>
      {day && pickedRunId != null && (
        <StepLane key={pickedRunId} runId={pickedRunId} run={runs.find((r) => r.id === pickedRunId) ?? null} locale={locale} />
      )}
      {!day && (
        <div className="mt-2 flex items-center justify-end gap-2 text-[10px] text-subtle-foreground">
          <span>{t("activityPage.chartTime")}</span>
          <span className="flex gap-[2px]" aria-hidden>
            {[25, 45, 65, 85, 100].map((p) => <span key={p} className="h-2 w-3 rounded-[2px]" style={{ background: tint(p) }} />)}
          </span>
          <span>{t("activityPage.more")}</span>
        </div>
      )}
    </div>
  );
}

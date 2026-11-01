import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pause, Play, SkipBack, X } from "lucide-react";
import { api } from "../../api/client";
import type { RunListItem, RunProcessOut } from "../../api/client.types";
import { utcIso } from "../../lib/conversationMeta";
import { stepWords } from "../../lib/process";
import { fmtMs } from "../../lib/usageFormat";
import { useActivityStore } from "../../stores/activityStore";

/** Board F: a run shorter than this still draws a bar this wide, so it can be seen and hit; packing counts the same width. */
export const MIN_BAR_MS = 14 * 60_000;
/** The lane stops growing here: what does not fit (a burst of parallel jobs) stacks into the last row. */
export const MAX_ROWS = 6;
/** How long the replay stays on each step. */
export const REPLAY_MS = 700;
/** The most runs one day's axis asks for: the server's page limit (GET /runs). */
const RUNS_LIMIT = 200;
const ROW_PX = 20;
const LABEL = "w-16 shrink-0 pr-2 text-right text-[10px] text-subtle-foreground";

export type Outcome = "ok" | "failed" | "waiting" | "running" | "stopped";
// A running bar pulses, as the list's running dot does, so it reads apart from the amber of one that waits (close in light themes).
const COLOUR: Record<Outcome, string> = {
  ok: "bg-success", failed: "bg-danger", waiting: "bg-warning", running: "bg-primary motion-safe:animate-pulse",
  stopped: "bg-subtle-foreground",
};
const WORD: Record<Outcome, string> = {
  ok: "activityPage.done", failed: "activityPage.failed", waiting: "activityPage.waitingRun", running: "activityPage.running",
  stopped: "activityPage.cancelled",
};

/** How a run ended, in the words and colours of the list below (ActivityView's dot), plus amber while it waits for your answer. */
export function outcomeOf(run: Pick<RunListItem, "status" | "waiting">): Outcome {
  if (run.status === "recording") return run.waiting ? "waiting" : "running";
  if (run.status === "failed") return "failed";
  if (run.status === "cancelled" || run.status === "interrupted") return "stopped";
  return "ok";
}

/** Each run goes into the first row that is free when it starts, so a row never overlaps; a short run counts as MIN_BAR_MS. */
export function packRows(runs: { id: number; start: number; end: number }[]): Map<number, number> {
  const rows = new Map<number, number>();
  const ends: number[] = [];
  for (const run of [...runs].sort((a, b) => a.start - b.start || a.id - b.id)) {
    let row = ends.findIndex((free) => free <= run.start);
    if (row < 0) row = Math.min(ends.length, MAX_ROWS - 1);
    ends[row] = Math.max(ends[row] ?? 0, run.end, run.start + MIN_BAR_MS);
    rows.set(run.id, row);
  }
  return rows;
}

const at = (time: string | null | undefined) => (time ? Date.parse(utcIso(time)) : NaN);
const pct = (n: number) => `${n.toFixed(2)}%`;
const clockOf = (locale: string) => new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" });

/** A run's span on the axis: from its start to its end, or to now while it runs. */
function spanOf(run: RunListItem, now: number): { start: number; end: number } {
  const start = at(run.created_at);
  return { start, end: run.status !== "recording" && run.total_ms != null ? start + run.total_ms : Math.max(start, now) };
}

/** The runs on a day's axis (GET /runs since its first hour). Nothing is asked for while the axis is off (7 and 30 days). */
export function useAxisRuns(t0: number, on: boolean): RunListItem[] {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  useEffect(() => {
    if (!on) return;
    let cancelled = false;
    api.listRuns({ since: Math.floor(t0 / 1000), limit: RUNS_LIMIT })
      .then((list) => { if (!cancelled) setRuns(list); })
      .catch(() => { /* keep the last bars */ });
    return () => { cancelled = true; };
  }, [t0, on]);
  return runs;
}

/** Above the axis: what a bar means until a run is picked, and the colours. */
export function AxisHead({ runs, picked }: { runs: RunListItem[]; picked: boolean }) {
  const { t } = useTranslation();
  // Stopped runs are rare: their colour is explained only when one is on the axis.
  const shown: Outcome[] = ["ok", "failed", "waiting", "running",
    ...(runs.some((run) => outcomeOf(run) === "stopped") ? ["stopped" as const] : [])];
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 pl-16 text-[10.5px] text-subtle-foreground">
      {!picked && <span className="text-muted-foreground">{t("activityPage.axisHint")}</span>}
      <span className="ml-auto flex flex-wrap items-center gap-x-3" data-testid="axis-legend">
        {shown.map((outcome) => (
          <span key={outcome} className="inline-flex items-center gap-1">
            <span aria-hidden className={`h-2 w-2 rounded-[2px] ${COLOUR[outcome]}`} />{t(WORD[outcome])}
          </span>
        ))}
      </span>
    </div>
  );
}

/**
 * INB7-b, board F's runs lane: one bar per run on the token row's axis (t0..t1, epoch ms). Its length is the time the run took
 * and its colour how it ended. Picking a bar shows that run's steps (StepLane); runs a filter of the list below leaves out are dimmed.
 */
export function RunsLane({ runs, t0, t1, locale }: { runs: RunListItem[]; t0: number; t1: number; locale: string }) {
  const { t } = useTranslation();
  const filter = useActivityStore((s) => s.filter);
  const axisRunId = useActivityStore((s) => s.axisRunId);
  const setAxisRun = useActivityStore((s) => s.setAxisRun);
  const clock = useMemo(() => clockOf(locale), [locale]);
  const placed = useMemo(() => {
    const now = Date.now();
    const spans = runs.map((run) => ({ run, ...spanOf(run, now) })).filter((s) => Number.isFinite(s.start));
    return { spans, rows: packRows(spans.map(({ run, start, end }) => ({ id: run.id, start, end }))) };
  }, [runs]);
  const width = t1 - t0;
  const rowCount = placed.rows.size ? Math.max(...placed.rows.values()) + 1 : 1;
  const filteredOut = (run: RunListItem, start: number) => (!!filter.model && run.model !== filter.model)
    || (filter.since != null && filter.until != null && (start < filter.since * 1000 || start >= filter.until * 1000));

  return (
    <div className="mt-3 flex" data-testid="axis-runs">
      <span className={`${LABEL} pt-1`}>{t("activityPage.kpiRuns")}</span>
      <div className="relative flex-1 rounded-[3px] bg-border/25" style={{ height: 8 + rowCount * ROW_PX }}>
        {placed.spans.map(({ run, start, end }) => {
          const from = Math.max(start, t0);
          const to = Math.min(Math.max(end, start + MIN_BAR_MS), t1);
          const outcome = outcomeOf(run);
          const picked = run.id === axisRunId;
          const dim = (axisRunId != null && !picked) || filteredOut(run, start);
          const took = outcome === "running" || outcome === "waiting" || run.total_ms == null ? "" : fmtMs(run.total_ms);
          return (
            <button key={run.id} type="button" data-testid={`axis-run-${run.id}`} data-row={placed.rows.get(run.id)}
              data-outcome={outcome} aria-pressed={picked}
              aria-label={[run.user_message || t("activityPage.run", { id: run.id }), clock.format(start), took, t(WORD[outcome])]
                .filter(Boolean).join(" · ")}
              onClick={() => setAxisRun(picked ? null : run.id)}
              className={`absolute h-3.5 rounded-[3px] outline-none focus-visible:ring-2 focus-visible:ring-primary/60 ${COLOUR[outcome]} ${
                picked ? "ring-2 ring-foreground ring-offset-1 ring-offset-background" : ""}`}
              style={{ left: pct(((from - t0) / width) * 100), width: pct((Math.max(0, to - from) / width) * 100),
                top: 4 + (placed.rows.get(run.id) ?? 0) * ROW_PX, opacity: dim ? 0.28 : 1 }} />
          );
        })}
      </div>
    </div>
  );
}

/**
 * INB7-b: the picked run's steps on a lane of their own, each where it started within the run, and a replay that walks through
 * them one at a time (REPLAY_MS each) and stops at the last. A step recorded before steps kept their time keeps its place in the
 * order. Keyed by the run, so picking another starts it fresh. The details still open in the drawer until INB7-c's inspector.
 */
export function StepLane({ runId, run, locale }: { runId: number; run: RunListItem | null; locale: string }) {
  const { t } = useTranslation();
  const setAxisRun = useActivityStore((s) => s.setAxisRun);
  const setOpenRun = useActivityStore((s) => s.setOpenRun);
  const clock = useMemo(() => clockOf(locale), [locale]);
  const [proc, setProc] = useState<RunProcessOut | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api.runProcess(runId).then((p) => { if (!cancelled) setProc(p); }).catch(() => { /* the lane stays hidden */ });
    return () => { cancelled = true; };
  }, [runId]);
  const steps = useMemo(() => (proc?.entries ?? []).filter((entry) => entry.kind === "tool"), [proc]);
  const total = steps.length;
  // Playing until the last step shows; then it stops by itself and the button offers the replay again.
  const live = playing && (step == null || step < total - 1);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setStep((s) => Math.min(total - 1, (s ?? -1) + 1)), REPLAY_MS);
    return () => clearInterval(timer);
  }, [live, total]);
  const toggle = () => {
    if (live) { setPlaying(false); return; }
    setStep((s) => (s == null || s >= total - 1 ? 0 : s));
    setPlaying(true);
  };
  const restart = () => { setPlaying(false); setStep(0); };

  const start = at(proc?.started_at ?? run?.created_at);
  const listedEnd = run && run.status !== "recording" && run.total_ms != null ? start + run.total_ms : NaN;
  const end = Math.max(proc?.ended_at ? at(proc.ended_at) : Number.isFinite(listedEnd) ? listedEnd : Date.now(), start + 1000);
  const place = (entry: (typeof steps)[number], i: number) => {
    const when = at(entry.at);
    const share = Number.isFinite(when) && Number.isFinite(start) ? (when - start) / (end - start) : (i + 0.5) / total;
    return Math.max(1.5, Math.min(97, share * 100));
  };
  const shown = step == null ? total : step + 1;
  const words = (entry: (typeof steps)[number]) => stepWords(
    { tool: entry.tool, argsSummary: entry.args_summary, status: entry.ok ? "ok" : "error", summary: entry.summary }, t);
  const current = step != null ? steps[step] : null;

  return (
    <div className="mt-3 border-t border-border pt-2">
      <div className="flex items-center gap-2 pl-16 text-[11px]">
        {total > 0 && (
          <>
            <button type="button" onClick={restart} aria-label={t("activityPage.restart")} title={t("activityPage.restart")}
              className="rounded p-1 text-muted-foreground hover:bg-foreground/5">
              <SkipBack size={12} aria-hidden />
            </button>
            <button type="button" onClick={toggle}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-foreground hover:bg-foreground/5">
              {live ? <Pause size={11} aria-hidden /> : <Play size={11} aria-hidden />}
              {t(live ? "activityPage.pause" : "activityPage.replay")}
            </button>
          </>
        )}
        {proc && (
          <span className="font-mono text-subtle-foreground" data-testid="axis-position">
            {total ? t("activityPage.stepOf", { n: shown, total }) : t("activityPage.noSteps")}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-right text-muted-foreground">
          {run?.user_message || t("activityPage.run", { id: runId })}
        </span>
        <button type="button" onClick={() => setOpenRun(runId)}
          className="rounded-md px-2 py-0.5 text-primary hover:bg-primary/10">{t("activityPage.openRun")}</button>
        <button type="button" onClick={() => setAxisRun(null)} aria-label={t("activityPage.allRuns")} title={t("activityPage.allRuns")}
          className="rounded p-1 text-muted-foreground hover:bg-foreground/5">
          <X size={12} aria-hidden />
        </button>
      </div>
      {proc && total > 0 && (
        <>
          <div className="mt-1.5 flex items-center" data-testid="axis-steps">
            <span className={LABEL}>{t("activityPage.chartSteps")}</span>
            <div className="relative h-5 flex-1">
              <span aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-border" />
              {steps.map((entry, i) => (
                <span key={i} data-testid={`axis-step-${i}`} data-ok={String(!!entry.ok)}
                  title={[Number.isFinite(at(entry.at)) ? clock.format(at(entry.at)) : "", words(entry)].filter(Boolean).join(" · ")}
                  className={`absolute top-1/2 h-3 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full ${entry.ok ? "bg-primary" : "bg-danger"}`}
                  style={{ left: pct(place(entry, i)), opacity: i < shown ? 1 : 0.25 }} />
              ))}
              <span aria-hidden className="absolute inset-y-0 w-px bg-foreground"
                style={{ left: pct(place(steps[shown - 1], shown - 1)) }} />
            </div>
          </div>
          <div className="mt-0.5 flex justify-between pl-16 font-mono text-[10px] text-subtle-foreground">
            <span>{Number.isFinite(start) ? clock.format(start) : ""}</span>
            <span>{proc.ended_at || Number.isFinite(listedEnd) ? clock.format(end) : t("activityPage.now")}</span>
          </div>
          {current && (
            <div className="mt-1 truncate pl-16 text-[11.5px] text-foreground" data-testid="axis-caption">
              {`${(step ?? 0) + 1}. ${words(current)}`}
              {Number.isFinite(at(current.at)) && <span className="ml-2 font-mono text-subtle-foreground">{clock.format(at(current.at))}</span>}
            </div>
          )}
        </>
      )}
    </div>
  );
}

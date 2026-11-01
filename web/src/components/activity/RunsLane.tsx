import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pause, Play, SkipBack } from "lucide-react";
import { api } from "../../api/client";
import type { RunListItem, RunProcessOut } from "../../api/client.types";
import { PROACTIVE_CHANGED } from "../../api/proactive";
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
export const COLOUR: Record<Outcome, string> = {
  ok: "bg-success", failed: "bg-danger", waiting: "bg-warning", running: "bg-primary motion-safe:animate-pulse",
  stopped: "bg-subtle-foreground",
};
export const WORD: Record<Outcome, string> = {
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

/** Each run goes into the first row that is free when it starts, so a row never overlaps; a short run counts as MIN_BAR_MS. When
 *  all MAX_ROWS rows are busy the run is stacked into the last one, and `stacked` counts those, for the lane to say so. */
export function packRows(runs: { id: number; start: number; end: number }[]): { rows: Map<number, number>; stacked: number } {
  const rows = new Map<number, number>();
  const ends: number[] = [];
  let stacked = 0;
  for (const run of [...runs].sort((a, b) => a.start - b.start || a.id - b.id)) {
    let row = ends.findIndex((free) => free <= run.start);
    if (row < 0 && ends.length < MAX_ROWS) row = ends.length;
    else if (row < 0) { row = MAX_ROWS - 1; stacked += 1; }
    ends[row] = Math.max(ends[row] ?? 0, run.end, run.start + MIN_BAR_MS);
    rows.set(run.id, row);
  }
  return { rows, stacked };
}

/** A server time (naive UTC, or with "Z") in epoch ms; NaN for none. */
export const at = (time: string | null | undefined) => (time ? Date.parse(utcIso(time)) : NaN);
const pct = (n: number) => `${n.toFixed(2)}%`;
export const clockOf = (locale: string) => new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" });

/** A run's span: to now only while it runs. A run the boot sweep interrupted has an end and no total (run_reaper), and one with
 *  neither draws its shortest bar rather than running on to now (⓪Plan's review of PR 622, 3). */
function spanOf(run: RunListItem, now: number): { start: number; end: number } {
  const start = at(run.created_at);
  if (run.status === "recording") return { start, end: Math.max(start, now) };
  if (run.total_ms != null) return { start, end: start + run.total_ms };
  const ended = at(run.ended_at);
  return { start, end: Number.isFinite(ended) ? ended : start };
}

/** Same cadence as the badge (useWaiting): every 30 s while the window shows, at once when it shows again, and when a card or a
 *  reminder changes, then once more a moment later, after the server has applied it. */
const POLL_MS = 30_000;
const AGAIN_MS = 1_500;

/** Reads now, then again on the badge's cadence, until `read` is null or the page goes. A read that a newer one overtook is dropped,
 *  so a late old answer never replaces a fresh one (⓪Plan's re-check of PR 622, B); a failed read keeps what is shown. `read` and
 *  `apply` must be stable (useCallback, a state setter). */
export function useFreshRead<T>(read: (() => Promise<T>) | null, apply: (value: T) => void): void {
  useEffect(() => {
    if (!read) return;
    let cancelled = false;
    let latest = 0;
    const load = () => {
      const mine = ++latest;
      read().then((value) => { if (!cancelled && mine === latest) apply(value); }).catch(() => { /* keep what is shown */ });
    };
    load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") load(); }, POLL_MS);
    let again: ReturnType<typeof setTimeout> | undefined;
    const onChange = () => { load(); clearTimeout(again); again = setTimeout(load, AGAIN_MS); };
    const onShown = () => { if (document.visibilityState !== "hidden") load(); };
    window.addEventListener(PROACTIVE_CHANGED, onChange);
    document.addEventListener("visibilitychange", onShown);
    return () => {
      cancelled = true; clearInterval(timer); clearTimeout(again);
      window.removeEventListener(PROACTIVE_CHANGED, onChange); document.removeEventListener("visibilitychange", onShown);
    };
  }, [read, apply]);
}

/** The runs on a day's axis (GET /runs since its first hour), and when they were read: a running bar reaches that moment. Nothing
 *  is asked for while the axis is off (7 and 30 days). */
export function useAxisRuns(t0: number, on: boolean): { runs: RunListItem[]; now: number } {
  const [shown, setShown] = useState<{ runs: RunListItem[]; now: number }>({ runs: [], now: 0 });
  const read = useCallback(() => api.listRuns({ since: Math.floor(t0 / 1000), limit: RUNS_LIMIT }), [t0]);
  const apply = useCallback((runs: RunListItem[]) => setShown({ runs, now: Date.now() }), []);
  useFreshRead(on ? read : null, apply);
  return shown;
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
export function RunsLane({ runs, now, t0, t1, locale }: { runs: RunListItem[]; now: number; t0: number; t1: number; locale: string }) {
  const { t } = useTranslation();
  const filter = useActivityStore((s) => s.filter);
  const pickedRunId = useActivityStore((s) => s.pickedRunId);
  const setPickedRun = useActivityStore((s) => s.setPickedRun);
  const clock = useMemo(() => clockOf(locale), [locale]);
  const placed = useMemo(() => {
    const spans = runs.flatMap((run) => {
      const { start, end } = spanOf(run, now);
      if (!Number.isFinite(start)) return [];
      // The newest runs keep their shortest bar too: at the right edge it reaches back from the axis's end (⓪Plan's review of
      // PR 622, 2). Rows are packed on what is drawn, so a bar moved back never lands on its neighbour.
      const from = Math.min(Math.max(start, t0), t1 - MIN_BAR_MS);
      return [{ run, start, from, to: Math.min(Math.max(end, from + MIN_BAR_MS), t1) }];
    });
    return { spans, ...packRows(spans.map(({ run, from, to }) => ({ id: run.id, start: from, end: to }))) };
  }, [runs, now, t0, t1]);
  const width = t1 - t0;
  const rowCount = placed.rows.size ? Math.max(...placed.rows.values()) + 1 : 1;
  const filteredOut = (run: RunListItem, start: number) => (!!filter.model && run.model !== filter.model)
    || (filter.since != null && filter.until != null && (start < filter.since * 1000 || start >= filter.until * 1000));

  return (
    <div className="mt-3 flex" data-testid="axis-runs">
      <span className={`${LABEL} relative pt-1`}>
        {t("activityPage.kpiRuns")}
        {/* More runs at once than the lane has rows: the rest are stacked in the last row, and this says how many. */}
        {placed.stacked > 0 && (
          <span data-testid="axis-overflow" className="absolute right-2 font-mono text-[10px] text-muted-foreground"
            style={{ top: 2 + (MAX_ROWS - 1) * ROW_PX }} aria-label={t("activityPage.overlapMore", { n: placed.stacked })}
            title={t("activityPage.overlapMore", { n: placed.stacked })}>+{placed.stacked}</span>
        )}
      </span>
      <div className="relative flex-1 rounded-[3px] bg-border/25" style={{ height: 8 + rowCount * ROW_PX }}>
        {placed.spans.map(({ run, start, from, to }) => {
          const outcome = outcomeOf(run);
          const picked = run.id === pickedRunId;
          const dim = (pickedRunId != null && !picked) || filteredOut(run, start);
          const took = outcome === "running" || outcome === "waiting" || run.total_ms == null ? "" : fmtMs(run.total_ms);
          return (
            <button key={run.id} type="button" data-testid={`axis-run-${run.id}`} data-row={placed.rows.get(run.id)}
              data-outcome={outcome} aria-pressed={picked}
              aria-label={[run.user_message || t("activityPage.run", { id: run.id }), clock.format(start), took, t(WORD[outcome])]
                .filter(Boolean).join(" · ")}
              onClick={() => setPickedRun(picked ? null : run.id, run)}
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

type Step = RunProcessOut["entries"][number];

/** A read of one run's steps shared by everyone who asks while it is in flight (the axis's lane and the inspector open together),
 *  then forgotten: a run's steps are written when it ends, so a later read must reach the server. */
const inflight = new Map<number, Promise<RunProcessOut>>();
function readSteps(runId: number): Promise<RunProcessOut> {
  let read = inflight.get(runId);
  if (!read) {
    read = api.runProcess(runId);
    inflight.set(runId, read);
    void read.finally(() => inflight.delete(runId)).catch(() => {});
  }
  return read;
}

/**
 * The picked run's steps (GET /runs/{id}/process), read again once the list says it stopped running: a run's steps are written
 * when it ends (run_recorder.finalize). With none, `empty` says why: not written yet while it runs (⓪Plan's review of PR 622, 1);
 * never written for a run the boot sweep interrupted, which has no total; a run that ended otherwise without a tool step stopped
 * before any (re-check, C); or it only replied.
 */
export function useRunSteps(runId: number, run: RunListItem | null): { proc: RunProcessOut | null; steps: Step[]; empty: string } {
  const [proc, setProc] = useState<RunProcessOut | null>(null);
  const running = run?.status === "recording";
  useEffect(() => {
    let cancelled = false;
    readSteps(runId).then((p) => { if (!cancelled) setProc(p); }).catch(() => { /* nothing to show */ });
    return () => { cancelled = true; };
  }, [runId, running]);
  const steps = useMemo(() => (proc?.entries ?? []).filter((entry) => entry.kind === "tool"), [proc]);
  const ended = proc?.status;
  const empty = ended === "recording" ? (run?.waiting ? "activityPage.stepsAfterAnswer" : "activityPage.stepsWhenDone")
    : ended === "interrupted" && run?.total_ms == null ? "activityPage.stepsNotSaved"
      : ended === "interrupted" || ended === "cancelled" || ended === "failed" ? "activityPage.stoppedNoSteps"
        : "activityPage.noSteps";
  return { proc, steps, empty };
}

/** A step in the words of the conversation's step list (lib/process.stepWords). */
export function stepText(entry: Step, t: (key: string, options?: Record<string, unknown>) => string): string {
  return stepWords({ tool: entry.tool, argsSummary: entry.args_summary, status: entry.ok ? "ok" : "error", summary: entry.summary }, t);
}

/**
 * INB7-b: the picked run's steps on a lane of their own, each where it started within the run, and a replay that walks through
 * them one at a time (REPLAY_MS each) and stops at the last. A step recorded before steps kept their time keeps its place in the
 * order. The replay's place lives in the store (INB7-c1), so the inspector's step list follows it and can move it; the run's
 * name, its details and letting it go are the inspector's (board F: one of each).
 */
export function StepLane({ runId, run, locale }: { runId: number; run: RunListItem | null; locale: string }) {
  const { t } = useTranslation();
  const step = useActivityStore((s) => s.replayStep);
  const playing = useActivityStore((s) => s.replayPlaying);
  const setReplay = useActivityStore((s) => s.setReplay);
  const clock = useMemo(() => clockOf(locale), [locale]);
  const { proc, steps, empty } = useRunSteps(runId, run);
  const total = steps.length;
  // Playing until the last step shows; then it stops by itself and the button offers the replay again.
  const live = playing && (step == null || step < total - 1);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => {
      const now = useActivityStore.getState().replayStep;
      setReplay({ step: Math.min(total - 1, (now ?? -1) + 1) });
    }, REPLAY_MS);
    return () => clearInterval(timer);
  }, [live, total, setReplay]);
  const toggle = () => {
    if (live) { setReplay({ playing: false }); return; }
    setReplay({ step: step == null || step >= total - 1 ? 0 : step, playing: true });
  };
  const restart = () => setReplay({ step: 0, playing: false });

  const start = at(proc?.started_at ?? run?.created_at);
  const listedEnd = run && run.status !== "recording" && run.total_ms != null ? start + run.total_ms : NaN;
  const end = Math.max(proc?.ended_at ? at(proc.ended_at) : Number.isFinite(listedEnd) ? listedEnd : Date.now(), start + 1000);
  const place = (entry: Step, i: number) => {
    const when = at(entry.at);
    const share = Number.isFinite(when) && Number.isFinite(start) ? (when - start) / (end - start) : (i + 0.5) / total;
    return Math.max(1.5, Math.min(97, share * 100));
  };
  const shown = step == null ? total : Math.min(step, total - 1) + 1;
  const words = (entry: Step) => stepText(entry, t);
  const current = step != null ? steps[step] ?? null : null;

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
            {total ? t("activityPage.stepOf", { n: shown, total }) : t(empty)}
          </span>
        )}
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

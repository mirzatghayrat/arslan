import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, ChevronRight, X } from "lucide-react";
import type { RunListItem } from "../../api/client.types";
import type { StepDetail } from "../../lib/process";
import { fmtMs } from "../../lib/usageFormat";
import { useActivityStore } from "../../stores/activityStore";
import { StepDetailView } from "../reply/ProcessList";
import { COLOUR, WORD, at, clockOf, outcomeOf, stepText, useRunSteps } from "./RunsLane";

/**
 * INB7-c1, board F's inspector beside 「最近的工作」: the picked run (a row or a bar picks it), its steps in the conversation's
 * words with their times, following the axis's replay and moving it when a step is clicked, each opening to its detail. "Details"
 * opens the drawer until INB7-c4 folds what it shows (scores, history) into this aside; 「改动」 and 「诊断」 come in INB7-c3/c4, and what
 * waits on you, shown when nothing is picked, in INB7-c5.
 */
export default function RunInspector({ runs }: { runs: RunListItem[] }) {
  const { t } = useTranslation();
  const pickedRunId = useActivityStore((s) => s.pickedRunId);
  const pickedRun = useActivityStore((s) => s.pickedRun);
  // The store's copy, which the axis keeps fresh over a day (it reads the runs every 30 s); else the loaded list's.
  const run = (pickedRun?.id === pickedRunId ? pickedRun : null) ?? runs.find((r) => r.id === pickedRunId) ?? null;
  return (
    <aside data-testid="run-inspector" aria-label={t("activityPage.details")}
      className="self-start rounded-lg border border-border bg-surface/40 p-4 lg:sticky lg:top-0">
      {pickedRunId == null
        ? <p className="text-xs text-muted-foreground">{t("activityPage.inspectorHint")}</p>
        : <Picked key={pickedRunId} runId={pickedRunId} run={run} />}
    </aside>
  );
}

function Picked({ runId, run }: { runId: number; run: RunListItem | null }) {
  const { t, i18n } = useTranslation();
  const setPickedRun = useActivityStore((s) => s.setPickedRun);
  const setOpenRun = useActivityStore((s) => s.setOpenRun);
  const step = useActivityStore((s) => s.replayStep);
  const setReplay = useActivityStore((s) => s.setReplay);
  const clock = useMemo(() => clockOf(i18n.language), [i18n.language]);
  const { proc, steps, empty } = useRunSteps(runId, run);
  const [open, setOpen] = useState<number | null>(null);
  const outcome = run ? outcomeOf(run) : null;
  const started = at(run?.created_at);
  const meta = [Number.isFinite(started) ? clock.format(started) : "",
    run?.total_ms != null && run.status !== "recording" ? fmtMs(run.total_ms) : "", outcome ? t(WORD[outcome]) : ""]
    .filter(Boolean).join(" · ");

  return (
    <section>
      <div className="flex items-start gap-2">
        <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${outcome ? COLOUR[outcome] : "bg-border"}`} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[13px] font-medium text-foreground">{run?.user_message || t("activityPage.run", { id: runId })}</h3>
          {meta && <p className="mt-0.5 text-[11px] text-subtle-foreground">{meta}</p>}
        </div>
        <button type="button" onClick={() => setOpenRun(runId)}
          className="shrink-0 rounded-md px-2 py-0.5 text-[11.5px] text-primary hover:bg-primary/10">{t("activityPage.details")}</button>
        <button type="button" onClick={() => setPickedRun(null)} aria-label={t("activityPage.allRuns")} title={t("activityPage.allRuns")}
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-foreground/5">
          <X size={12} aria-hidden />
        </button>
      </div>

      <div className="mt-4 text-[10.5px] font-medium uppercase tracking-wide text-subtle-foreground">
        {t("activityPage.replay")}{steps.length ? ` · ${steps.length}` : ""}
      </div>
      {proc && !steps.length && <p className="mt-2 text-xs text-muted-foreground">{t(empty)}</p>}
      <ol className="mt-2 space-y-0.5">
        {steps.map((entry, i) => {
          const when = at(entry.at);
          const current = step === i;
          return (
            <li key={i} data-testid={`inspector-step-${i}`} data-ok={String(!!entry.ok)} aria-current={current ? "step" : undefined}
              data-ahead={String(step != null && i > step)}
              className={`rounded-md ${current ? "bg-primary/10" : ""} ${step != null && i > step ? "opacity-40" : ""}`}>
              <div className="flex items-center gap-1">
                {/* A click moves the axis's replay here and takes over from the player. */}
                <button type="button" onClick={() => setReplay({ step: i, playing: false })}
                  className="flex min-w-0 flex-1 items-center gap-2 px-1.5 py-1 text-left text-[12px]">
                  <span className="w-4 shrink-0 text-right font-mono text-[10.5px] text-subtle-foreground">{i + 1}</span>
                  {entry.ok ? <Check className="h-3 w-3 shrink-0 text-success" aria-hidden /> : <X className="h-3 w-3 shrink-0 text-danger" aria-hidden />}
                  <span className="min-w-0 flex-1 truncate text-foreground">{stepText(entry, t)}</span>
                  {Number.isFinite(when) && <span className="shrink-0 font-mono text-[10.5px] text-subtle-foreground">{clock.format(when)}</span>}
                </button>
                {entry.detail && (
                  <button type="button" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}
                    aria-label={`${t("activityPage.showDetail")}: ${stepText(entry, t)}`} className="shrink-0 rounded p-1 text-subtle-foreground hover:bg-foreground/5">
                    {open === i ? <ChevronDown className="h-3 w-3" aria-hidden /> : <ChevronRight className="h-3 w-3" aria-hidden />}
                  </button>
                )}
              </div>
              {open === i && (
                <div className="pb-1.5 pl-8 pr-1.5"><StepDetailView detail={entry.detail as StepDetail} raw={entry.raw} /></div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

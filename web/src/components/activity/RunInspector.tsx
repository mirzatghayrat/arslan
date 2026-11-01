import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, ChevronRight, X } from "lucide-react";
import { api } from "../../api/client";
import type { RunChangesOut, RunListItem } from "../../api/client.types";
import { baseName } from "../../lib/fileKinds";
import type { StepDetail } from "../../lib/process";
import { fmtMs } from "../../lib/usageFormat";
import { useActivityStore } from "../../stores/activityStore";
import { isolate } from "../CapabilitySwitches";
import { StepDetailView } from "../reply/ProcessList";
import DiffReader, { opensDiff } from "../workbench/DiffReader";
import { COLOUR, WORD, at, clockOf, outcomeOf, stepText, useFreshRead, useRunSteps } from "./RunsLane";

/**
 * INB7-c1, board F's inspector beside 「最近的工作」: the picked run (a row or a bar picks it), its steps in the conversation's
 * words with their times, following the axis's replay and moving it when a step is clicked, each opening to its detail; and
 * 「改动」, what it changed (INB7-c3). "Details" opens the drawer until INB7-c4 folds what it shows (scores, history) into this aside
 * with 「诊断」, and what
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
  const [tab, setTab] = useState<Tab>("replay");
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ replay: null, changes: null });
  const changes = useRunChanges(runId, (proc?.status ?? run?.status) === "recording");
  // WAI-ARIA tabs (⓪Plan's review of PR 629, 3): the arrows, Home and End move the selection and the focus; one tab is in the tab
  // order (roving tabindex).
  const onTabKey = (e: React.KeyboardEvent) => {
    const at = TABS.indexOf(tab);
    const next = e.key === "ArrowRight" ? TABS[(at + 1) % TABS.length] : e.key === "ArrowLeft" ? TABS[(at + TABS.length - 1) % TABS.length]
      : e.key === "Home" ? TABS[0] : e.key === "End" ? TABS[TABS.length - 1] : null;
    if (!next) return;
    e.preventDefault();
    setTab(next);
    tabRefs.current[next]?.focus();
  };
  // Once its steps' read says it has ended, that read is the fresher word on how and how long, over 7 and 30 days too, where
  // the list it was picked from is not read again (⓪Plan's re-check of PR 624).
  const settled = proc && proc.status !== "recording" ? proc : null;
  const outcome = settled ? outcomeOf({ status: settled.status }) : run ? outcomeOf(run) : null;
  const took = settled?.started_at && settled.ended_at ? at(settled.ended_at) - at(settled.started_at)
    : run?.total_ms != null && run.status !== "recording" ? run.total_ms : NaN;
  const started = at(run?.created_at ?? settled?.started_at);
  const meta = [Number.isFinite(started) ? clock.format(started) : "", Number.isFinite(took) ? fmtMs(took) : "",
    outcome ? t(WORD[outcome]) : ""].filter(Boolean).join(" · ");

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

      {/* Board F's tabs over the picked run: 「回放」 first, 「改动」 (INB7-c3); 「诊断」 comes in INB7-c4. */}
      <div role="tablist" aria-label={t("activityPage.details")} onKeyDown={onTabKey} className="mt-4 flex gap-1 border-b border-border">
        {TABS.map((id) => {
          const count = id === "replay" ? steps.length : changes.data?.state === "kept" ? changes.data.paths.length : 0;
          return (
            <button key={id} ref={(el) => { tabRefs.current[id] = el; }} type="button" role="tab" id={`inspector-tab-${id}`}
              aria-selected={tab === id} aria-controls={`inspector-panel-${id}`} tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)}
              className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-2 py-1 text-[11.5px] outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                tab === id ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              {t(TAB_WORD[id])}{count > 0 && <span className="font-mono text-[10.5px] text-subtle-foreground">{count}</span>}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`inspector-panel-${tab}`} aria-labelledby={`inspector-tab-${tab}`}>
      {tab === "changes" ? (
        <RunChanges runId={runId} changes={changes} />
      ) : (
      <>
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
                {/* A click moves the axis's replay here and takes over from the player; on the marked step it shows every step
                    again, the way back where there is no axis (7 and 30 days). */}
                <button type="button" onClick={() => setReplay({ step: current ? null : i, playing: false })}
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
      </>
      )}
      </div>
    </section>
  );
}

type Tab = "replay" | "changes";
const TABS: Tab[] = ["replay", "changes"];
const TAB_WORD: Record<Tab, string> = { replay: "activityPage.replay", changes: "activityPage.changesTab" };
/** While a run's changes are still being recorded, they are read again on the badge's beat this many times at most. */
const FINISHING_READS = 4;

/** `stuck`: it still says "finishing" after FINISHING_READS reads, so the tab stops reading and stops saying "Saving…". */
type RunChangesView = { data: RunChangesOut | null; failed: boolean; stuck?: boolean };

/** INB7-c3: what one run changed (GET /runs/{id}/changes), read again when it stops running (a checkpoint is recorded as it
 *  ends) and, while it says "finishing", on the badge's beat a few times (⓪Plan's review of PR 629). */
function useRunChanges(runId: number, running: boolean): RunChangesView {
  const [view, setView] = useState<RunChangesView>({ data: null, failed: false });
  const [finishingReads, setFinishingReads] = useState(0);
  const read = useCallback(() => api.runChanges(runId), [runId]);
  useEffect(() => {
    let alive = true;
    read().then((data) => { if (alive) setView({ data, failed: false }); })
      .catch(() => { if (alive) setView((prev) => (prev.data ? prev : { data: null, failed: true })); });
    return () => { alive = false; };
  }, [read, running]);
  const apply = useCallback((data: RunChangesOut) => {
    setView({ data, failed: false });
    setFinishingReads((n) => (data.state === "finishing" ? n + 1 : 0));
  }, []);
  useFreshRead(view.data?.state === "finishing" && finishingReads < FINISHING_READS ? read : null, apply);
  return { ...view, stuck: view.data?.state === "finishing" && finishingReads >= FINISHING_READS };
}

const KIND_COLOR = { made: "text-success", edited: "text-muted-foreground", deleted: "text-danger" } as const;
const STATE_WORD: Record<Exclude<RunChangesOut["state"], "kept">, string> = {
  running: "activityPage.changesWhenDone", finishing: "activityPage.changesSaving", interrupted: "activityPage.changesInterrupted",
  none: "activityPage.noChanges",
  expired: "activityPage.changesExpired", not_saved: "activityPage.changesNotSaved",
};

/**
 * INB7-c3, board F's 「改动」: what the picked run changed in your folders, from its own checkpoint, in the Overview's words; each
 * text path opens the DIFF1 side-by-side reader in place. A turn that was undone, or a path with no line diff (an image, say), is
 * listed without opening. Every other state says what it is: still running, being recorded, nothing changed, its record gone after
 * 7 days, or its folder not saved; and so do a read in flight and one that failed.
 */
function RunChanges({ runId, changes }: { runId: number; changes: RunChangesView }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<{ folder: string; path: string } | null>(null);
  const { data, failed } = changes;
  const note = (key: string) => <p className="mt-2 text-xs text-muted-foreground">{t(key)}</p>;
  if (!data) return note(failed ? "activityPage.changesFailed" : "activityPage.changesLoading");
  if (open) {
    return <div className="mt-2"><DiffReader conversationId={data.conversation_id} runId={runId} folder={open.folder} path={open.path}
      onBack={() => setOpen(null)} /></div>;
  }
  if (changes.stuck) return note("activityPage.changesNotYet");
  if (data.state !== "kept") return note(STATE_WORD[data.state]);
  return (
    <div className="mt-2">
      {data.undone && <span className="rounded bg-fill px-1.5 text-[10.5px] text-muted-foreground">{t("workbench.undone")}</span>}
      <ul className="mt-1 space-y-0.5">
        {data.paths.map((p) => {
          const name = baseName(p.path);
          const dir = p.path.slice(0, Math.max(0, p.path.length - name.length - 1));
          const parts = <>
            <span className={`min-w-12 shrink-0 text-[11px] ${KIND_COLOR[p.kind]}`}>{t(`workbench.${p.kind}`)}</span>
            <span className="min-w-0 truncate">{isolate(name)}</span>
            {dir && <span className="min-w-0 flex-1 truncate text-[11px] text-subtle-foreground" dir="rtl">{isolate(dir)}</span>}
          </>;
          const line = "flex w-full min-w-0 items-center gap-2 px-1.5 py-1 text-[12px]";
          return (
            <li key={`${p.folder}/${p.path}`} data-testid="inspector-change" title={isolate(`${p.folder}/${p.path}`)}>
              {!data.undone && opensDiff(p.path)
                ? <button type="button" onClick={() => setOpen({ folder: p.folder, path: p.path })}
                  className={`${line} rounded-md text-left hover:bg-foreground/[0.04]`}>
                  {parts}<ChevronRight className="ml-auto h-3 w-3 shrink-0 text-subtle-foreground" aria-hidden /></button>
                : <div className={line}>{parts}</div>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

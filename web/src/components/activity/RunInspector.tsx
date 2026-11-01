import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, ChevronRight, X } from "lucide-react";
import type { RunListItem } from "../../api/client.types";
import { filesApi, type ConversationChangeTurn } from "../../api/files";
import { baseName } from "../../lib/fileKinds";
import type { StepDetail } from "../../lib/process";
import { fmtMs } from "../../lib/usageFormat";
import { useActivityStore } from "../../stores/activityStore";
import { isolate } from "../CapabilitySwitches";
import { StepDetailView } from "../reply/ProcessList";
import DiffReader, { opensDiff } from "../workbench/DiffReader";
import { COLOUR, WORD, at, clockOf, outcomeOf, stepText, useRunSteps } from "./RunsLane";

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
  const [tab, setTab] = useState<"replay" | "changes">("replay");
  // INB7-c3: what this run changed, from its own conversation's changes (read once it is known, and again when the run ends:
  // a checkpoint is written at the end). undefined while reading, null when it changed nothing.
  const conversationId = proc?.conversation_id ?? null;
  const [turn, setTurn] = useState<ConversationChangeTurn | null | undefined>(undefined);
  useEffect(() => {
    if (!conversationId) return;
    let alive = true;
    filesApi.changes(conversationId)
      .then((found) => { if (alive) setTurn(found.turns.find((x) => x.run_id === runId) ?? null); })
      .catch(() => { if (alive) setTurn(null); });
    return () => { alive = false; };
  }, [conversationId, runId, proc?.status]);
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
      <div role="tablist" aria-label={t("activityPage.details")} className="mt-4 flex gap-1 border-b border-border">
        {([["replay", "activityPage.replay", steps.length], ["changes", "activityPage.changesTab", turn?.paths.length ?? 0]] as const)
          .map(([id, word, count]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
              className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-2 py-1 text-[11.5px] ${
                tab === id ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              {t(word)}{count > 0 && <span className="font-mono text-[10.5px] text-subtle-foreground">{count}</span>}
            </button>
          ))}
      </div>
      {tab === "changes" ? (
        <RunChanges conversationId={proc?.conversation_id ?? null} runId={runId} turn={turn} />
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
    </section>
  );
}

const KIND_COLOR = { made: "text-success", edited: "text-muted-foreground", deleted: "text-danger" } as const;

/**
 * INB7-c3, board F's 「改动」: what the picked run changed in your folders, as the Overview's Changes lists it (one turn of its
 * conversation's GET /conversations/{id}/changes), each text path opening the DIFF1 side-by-side reader in place. A turn that was
 * undone, or a path with no line diff (an image, say), is listed without opening.
 */
function RunChanges({ conversationId, runId, turn }: { conversationId: string | null; runId: number; turn: ConversationChangeTurn | null | undefined }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<{ folder: string; path: string } | null>(null);
  if (open && conversationId) {
    return <div className="mt-2"><DiffReader conversationId={conversationId} runId={runId} folder={open.folder} path={open.path}
      onBack={() => setOpen(null)} /></div>;
  }
  if (turn === undefined) return null;
  if (!turn || !turn.paths.length) return <p className="mt-2 text-xs text-muted-foreground">{t("activityPage.noChanges")}</p>;
  return (
    <div className="mt-2">
      {turn.undone && <span className="rounded bg-fill px-1.5 text-[10.5px] text-muted-foreground">{t("workbench.undone")}</span>}
      <ul className="mt-1 space-y-0.5">
        {turn.paths.map((p) => {
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
              {!turn.undone && opensDiff(p.path)
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

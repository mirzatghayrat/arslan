import { useEffect, useRef, useState } from "react";
import { ClipboardCheck, RefreshCw, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import { tasksApi, type TaskAction, type TaskDetail, type TaskSummary } from "../../api/tasks";
import { useArslanStore } from "../../stores/arslanStore";
import CompanionDialog, { buttonClass, inputClass, primaryClass } from "./CompanionDialog";
import { companionError, taskErrorKey } from "./errors";
import RunReplay from "../RunReplay";
import TaskWorkers from "./TaskWorkers";
import TaskValidation from "./TaskValidation";
import MemoryEvidence from "./MemoryEvidence";

export function taskReason(reason: string | null) {
  return taskErrorKey(reason ?? "") ?? "tasks.reviewIntro";
}

export default function TaskPanel({ conversationId, onResume, compact = false }: {
  conversationId: string; onResume: (task: TaskSummary) => void; compact?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const frame = useArslanStore(state => state.taskState);
  const streamError = useArslanStore(state => state.error);
  const relevantFrame = frame?.conversation_id === conversationId ? frame : null;
  const [rows, setRows] = useState<TaskSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [more, setMore] = useState(false);
  const [ack, setAck] = useState(false);
  const [review, setReview] = useState<TaskAction | null>(null);
  const [applied, setApplied] = useState<boolean | null>(null);
  const [note, setNote] = useState("");
  const [replayRunId, setReplayRunId] = useState<number | null>(null);
  const resumeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resuming = useRef<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; if (resumeTimer.current) clearTimeout(resumeTimer.current); };
  }, []);
  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => {
      tasksApi.list(conversationId).then(next => {
        if (!alive) return;
        setRows(old => {
          const merged = next.map(row => {
            const cached = old.find(item => item.spec.id === row.spec.id);
            return cached && cached.state.sequence > row.state.sequence ? cached : row;
          });
          return open ? [...merged, ...old.filter(row => !next.some(item => item.spec.id === row.spec.id))] : merged;
        });
        setMore(next.length === 20);
        setSelected(value => value ?? next[0]?.spec.id ?? null);
      }).catch(() => { if (alive) setError("brain.read_failed"); });
    }, 100);
    return () => { alive = false; clearTimeout(timer); };
  }, [conversationId, relevantFrame?.task_id, relevantFrame?.sequence, refresh, open]);
  useEffect(() => {
    if (!open || !selected) return;
    let alive = true;
    setDetail(null); setAck(false); setReview(null);
    tasksApi.detail(selected).then(value => { if (alive) setDetail(value); })
      .catch(() => { if (alive) setError("brain.read_failed"); });
    return () => { alive = false; };
  }, [open, selected, refresh]);
  useEffect(() => {
    if (!open || !selected || busy || review || relevantFrame?.task_id !== selected) return;
    let alive = true;
    const timer = setTimeout(() => {
      tasksApi.detail(selected).then(value => { if (alive) setDetail(value); }).catch(() => {});
    }, 100);
    return () => { alive = false; clearTimeout(timer); };
  }, [open, selected, busy, review, relevantFrame?.task_id, relevantFrame?.sequence]);
  useEffect(() => {
    if (!resuming.current) return;
    if (relevantFrame?.task_id === resuming.current && relevantFrame.phase === "running") {
      if (resumeTimer.current) clearTimeout(resumeTimer.current);
      resuming.current = null; setBusy(false); setOpen(false); setRefresh(value => value + 1);
    } else if (streamError) {
      if (resumeTimer.current) clearTimeout(resumeTimer.current);
      resuming.current = null; setBusy(false); setError(taskErrorKey(streamError) ?? "companion.failure"); setRefresh(value => value + 1);
    }
  }, [relevantFrame, streamError]);
  const latest = rows[0];
  const phase = relevantFrame && relevantFrame.task_id === latest?.spec.id &&
    relevantFrame.sequence > latest.state.sequence ? relevantFrame.phase : latest?.state.phase;
  const active = phase === "running" || phase === "verifying";
  const unresolved = detail?.actions.filter(action => action.effect !== "read" && ["prepared", "in_flight", "uncertain"].includes(action.status)) ?? [];

  async function perform(operation: () => Promise<TaskSummary>) {
    setBusy(true); setError(null);
    try {
      const updated = await operation();
      const full = await tasksApi.detail(updated.spec.id);
      if (!mounted.current) return;
      setDetail(full); setRows(old => old.some(row => row.spec.id === full.spec.id)
        ? old.map(row => row.spec.id === full.spec.id ? full : row) : [full, ...old]);
      setReview(null); setAck(false); setNote(""); setApplied(null);
    } catch (cause) { if (mounted.current) setError(companionError(cause)); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function loadMore() {
    setBusy(true); setError(null);
    try {
      const next = await tasksApi.list(conversationId, rows.length);
      if (mounted.current) { setRows(old => [...old, ...next.filter(row => !old.some(item => item.spec.id === row.spec.id))]); setMore(next.length === 20); }
    } catch { if (mounted.current) setError("brain.read_failed"); }
    finally { if (mounted.current) setBusy(false); }
  }
  function resume() {
    if (!detail) return;
    setBusy(true); setError(null); resuming.current = detail.spec.id;
    onResume(detail);
    resumeTimer.current = setTimeout(() => {
      if (!mounted.current) return;
      resuming.current = null; setBusy(false); setError("tasks.resumeNotStarted"); setRefresh(value => value + 1);
    }, 8000);
  }
  if (!latest && !relevantFrame) return null;
  return <div className={compact ? "flex min-w-0 items-center gap-3 text-xs" : "flex shrink-0 items-center justify-between gap-3 border-b border-border/50 px-5 py-2 text-xs"}>
    <button className="inline-flex min-w-0 items-center gap-2 text-muted-foreground hover:text-foreground"
      onClick={() => { setSelected(latest?.spec.id ?? relevantFrame?.task_id ?? null); setError(null); setOpen(true); }}>
      <ClipboardCheck size={14} /><span>{t("tasks.taskStatus")}</span><span className="truncate">{t(`tasks.${phase ?? relevantFrame?.phase ?? "queued"}`)}</span>
    </button>
    {active && latest && <button className="inline-flex items-center gap-1 text-destructive disabled:opacity-50" disabled={busy}
      onClick={() => void perform(() => tasksApi.cancel(latest))}><Square size={12} />{t("tasks.stop")}</button>}
    {open && <CompanionDialog title={t("tasks.taskStatus")} onClose={() => setOpen(false)} busy={busy}>
      <div className="space-y-4 text-sm">
        <div className="flex gap-2"><select className={inputClass} aria-label={t("tasks.chooseTask")} value={selected ?? ""} disabled={busy}
          onChange={event => setSelected(event.target.value)}>{rows.map(row => <option key={row.spec.id} value={row.spec.id}>
            {row.spec.instruction.slice(0, 72)}
          </option>)}</select><button className={buttonClass} disabled={busy} aria-label={t("companion.refresh")} onClick={() => { setError(null); setRefresh(value => value + 1); }}><RefreshCw size={14} /></button></div>
        {more && <button className={buttonClass} disabled={busy} onClick={() => void loadMore()}>{t("companion.loadMore")}</button>}
        {error && <p role="alert" className="text-destructive">{t(error)}</p>}
        {!detail && !error && <p role="status">{t("companion.loading")}</p>}
        {detail && <>
          <p className="whitespace-pre-wrap break-words rounded-lg bg-foreground/5 p-3">{detail.spec.instruction}</p>
          <p className="font-medium">{t(`tasks.${detail.state.phase}`)}</p>
          <p className="text-xs leading-relaxed text-muted-foreground">{t(taskReason(detail.pause_reason))}</p>
          <TaskWorkers workers={detail.workers ?? []} onOpenRun={id => { setOpen(false); setReplayRunId(id); }} />
          <TaskValidation task={detail} />
          <MemoryEvidence conversationId={detail.conversation_id} taskId={detail.spec.id} />
          <div className="rounded-lg border border-border p-3"><h3 className="mb-2 font-medium">{t("tasks.budget")}</h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">{([
              ["model_requests", "requests"], ["tool_calls", "tools"], ["tokens", "tokens"], ["wall_seconds", "seconds"],
            ] as const).map(([key, label]) => <div key={key} className="flex flex-wrap justify-between gap-1"><dt className="text-muted-foreground">{t(`tasks.${label}`)}</dt>
              <dd>{new Intl.NumberFormat(i18n.resolvedLanguage, { maximumFractionDigits: 1 }).format(detail.budget.used[key] ?? 0)} / {detail.budget.limits[key]}</dd></div>)}</dl>
          </div>
          <p className="text-xs text-muted-foreground">{t("tasks.attempts")}: {detail.attempts.length} · {t("tasks.completedSteps")}: {detail.checkpoint?.progress.completed_steps.length ?? 0} · {t("tasks.artifacts")}: {detail.checkpoint?.progress.artifacts.length ?? 0}</p>
          <div className="flex flex-wrap gap-2">{detail.attempts.flatMap(attempt => attempt.run_ids.map(runId =>
            <button key={runId} className={buttonClass} disabled={busy}
              onClick={() => { setOpen(false); setReplayRunId(runId); }}>{t("tasks.openAttempt", { number: attempt.number })} · #{runId}</button>
          ))}</div>
          {!!unresolved.length && <div className="space-y-3 rounded-lg border border-amber-500/40 p-3">
            <h3 className="font-medium">{t("tasks.uncertain")}</h3>
            {unresolved.map(action => <div key={action.id} className="flex flex-wrap items-center justify-between gap-2">
              <span className="break-all text-xs">{action.tool_key}</span>{action.status === "uncertain" && <button className={buttonClass} disabled={busy || active}
                onClick={() => { setReview(action); setNote(""); setApplied(null); }}>{t("tasks.reviewAction")}</button>}
            </div>)}
          </div>}
          {review && <fieldset className="space-y-3 rounded-lg border border-primary/30 p-3">
            <legend className="px-1">{t("tasks.manualProof")}</legend><p className="text-xs text-muted-foreground">{t("tasks.reviewHint")}</p>
            {([true, false] as const).map(value => <label key={String(value)} className="flex items-start gap-2">
              <input type="radio" name="reconciliation" disabled={busy} checked={applied === value} onChange={() => setApplied(value)} />{t(value ? "tasks.applied" : "tasks.notApplied")}
            </label>)}
            <label className="block">{t("tasks.reviewNote")}<textarea className={`${inputClass} mt-1`} rows={3} maxLength={2000} value={note} disabled={busy} onChange={event => setNote(event.target.value)} /></label>
            <button className={primaryClass} disabled={busy || applied === null || note.trim().length < 10}
              onClick={() => void perform(() => tasksApi.reconcile(detail.spec.id, review, applied!, note.trim()))}>{t("tasks.recordReview")}</button>
          </fieldset>}
          {detail.state.phase === "waiting_user" && detail.pause_reason === "acceptance_review_required" && !unresolved.length &&
            detail.spec.acceptance.some(check => check.evaluator === "human") &&
            detail.spec.acceptance.every(check => check.evaluator === "human" || detail.state.results.some(result => result.check_id === check.id && ["passed", "not_applicable"].includes(result.status))) && <div className="space-y-3">
              <label className="flex items-start gap-2"><input type="checkbox" checked={ack} disabled={busy} onChange={event => setAck(event.target.checked)} />{t("tasks.acceptAck")}</label>
              <button className={primaryClass} disabled={busy || !ack} onClick={() => void perform(() => tasksApi.accept(detail))}>{t("tasks.accept")}</button>
            </div>}
          {["queued", "waiting_user", "failed", "cancelled"].includes(detail.state.phase) && detail.pause_reason !== "acceptance_review_required" &&
            <div className="space-y-2"><p className="text-xs text-muted-foreground">{t("tasks.resumeHint")}</p>
              <button className={primaryClass} disabled={busy || active || !!unresolved.length || detail.pause_reason === "task_budget_exhausted"} onClick={resume}>{t("tasks.resume")}</button></div>}
        </>}
      </div>
    </CompanionDialog>}
    {replayRunId !== null && <RunReplay runId={replayRunId} onClose={() => { setReplayRunId(null); setOpen(true); }} />}
  </div>;
}

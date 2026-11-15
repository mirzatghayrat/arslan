import { useState } from "react";
import { Check, Circle, Loader2, MessageSquare, Pause, Pencil, Play, Square, Target, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { backgroundJobsApi } from "../api/tasks";
import type { GoalCheckState, JobCard as Job } from "../api/client.types";
import { useArslanStore } from "../stores/arslanStore";

// L7-6: a goal's card, its edit step and the composer chip, as the mock the user approved on 2026-11-11 shows them
// (docs/plans/0164/L7-goal-mode.md, UI). The card only shows the server's `goal_state`; every control is a `/goal`
// line sent as an ordinary chat message (Stop on a running goal is the job's own stop).
export type SendLine = (text: string) => void;

const btn = "inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] hover:bg-foreground/5 disabled:opacity-50";
const primary = "inline-flex items-center gap-1 rounded-md border border-foreground bg-foreground px-2 py-1 text-[11px] font-semibold text-background hover:opacity-90 disabled:opacity-50";
const input = "min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1 text-[11px] text-foreground";

/** The objective without its `check:` lines, which the checks list shows. */
export function objectiveOf(goal: string): string {
  return goal.split(/(?:^|\s)`?check:/i)[0].trim() || goal;     // a word ending in "check:" is not one
}

function CheckIcon({ status }: { status: string }) {
  if (status === "passed") return <Check size={12} className="mt-0.5 shrink-0 text-success" aria-hidden />;
  if (status === "failed") return <X size={12} className="mt-0.5 shrink-0 text-danger" aria-hidden />;
  return <Circle size={10} className="mt-1 shrink-0 text-muted-foreground" aria-hidden />;
}

function Checks({ checks }: { checks: GoalCheckState[] }) {
  const { t } = useTranslation();
  return <ul className="mt-1 space-y-0.5">{checks.map((c) => {
    const r = c.receipt;
    const receipt = r ? [r.path, r.exit_code != null ? t("jobs.goal.exited", { code: String(r.exit_code) }) : null,
      r.count != null ? t("jobs.goal.found", { count: String(r.count) }) : null].filter(Boolean).join(" · ") : "";
    return <li key={c.id} data-testid={`goal-check-${c.id}`} className="flex items-start gap-1.5">
      <CheckIcon status={c.status} />
      <div className="min-w-0">{c.description} <span className="text-muted-foreground">
        · {c.user_confirmed ? t("jobs.goal.yours") : t(`jobs.check.${c.status}`, { defaultValue: c.status })}</span>
        {receipt && <span className="block break-words font-mono text-[10.5px] text-muted-foreground">{receipt}</span>}
      </div>
    </li>;
  })}</ul>;
}

interface Row { id: string | null; text: string; kind: GoalCheckState["kind"]; mine: boolean; flagged: boolean; outputs: string[] }

const rowOf = (c: GoalCheckState): Row => ({ id: c.id, kind: c.kind, mine: c.user_confirmed, flagged: c.flagged,
  outputs: c.outputs, text: c.kind === "check" ? c.description.replace(/^check:\s*/i, "") : c.description });

/** The form as `/goal edit` lines (the card's grammar). */
export function editLines(goal: string, rows: Row[], start: boolean): string {
  return [`/goal edit${start ? " start" : ""}`, `objective: ${objectiveOf(goal).replace(/\s+/g, " ")}`,
    ...rows.filter((r) => r.text.trim()).map((r) => r.kind === "check"
      ? `check: ${r.text.trim()}${r.outputs.length ? ` outputs: ${r.outputs.join(" ")}` : ""}`
      : `${r.id ?? "new"}${r.mine ? " (mine)" : ""}: ${r.text.trim().replace(/\s+/g, " ")}`)].join("\n");
}

function GoalForm({ job, started, onSend, onClose }: { job: Job; started: boolean; onSend?: SendLine; onClose: () => void }) {
  const { t } = useTranslation();
  const initial = job.goalState!.checks.map(rowOf);
  const [rows, setRows] = useState<Row[]>(initial);
  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const blocked = rows.some((r) => r.text.trim() && r.flagged && !r.mine);
  const changed = editLines(job.goal, rows, false) !== editLines(job.goal, initial, false);
  function start() {
    onSend?.(started || changed ? editLines(job.goal, rows, true) : "/goal start");
  }
  return <section data-testid="goal-form" data-goal-card={job.jobId} aria-label={t("jobs.goal.kickerEdit")}
    className="my-2 rounded-xl border border-primary/40 bg-surface/60 px-4 py-3 text-xs">
    <header className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{t("jobs.goal.kickerEdit")}</div>
        <div className="break-words font-medium text-foreground">{objectiveOf(job.goal)}</div>
      </div>
      <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px]">{t("jobs.goal.status.not_started")}</span>
    </header>
    <div className="mt-2 text-[10px] text-muted-foreground">{t("jobs.doneWhen")}</div>
    <div className="mt-1 grid gap-1.5">{rows.map((r, i) => <div key={i} className="grid gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <input type="text" className={input} aria-label={t("jobs.goal.check", { n: String(i + 1) })} value={r.text}
          onChange={(e) => set(i, { text: e.target.value })} />
        <span className="whitespace-nowrap text-[10px] text-muted-foreground">{t(`jobs.goal.kind.${r.kind}`)}
          {r.outputs.length > 0 && ` · ${t("jobs.goal.outputs", { outputs: r.outputs.join(", ") })}`}</span>
        <button type="button" className={btn} aria-label={t("jobs.goal.removeN", { n: String(i + 1) })}
          onClick={() => setRows(rows.filter((_, j) => j !== i))}>{t("jobs.goal.remove")}</button>
      </div>
      {r.flagged && <label className="flex items-center gap-1.5 text-[10.5px] text-warning">
        <input type="checkbox" checked={r.mine} onChange={(e) => set(i, { mine: e.target.checked })} />
        <span>{t("jobs.goal.flagged")} {t("jobs.goal.mine")}</span></label>}
    </div>)}</div>
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <button type="button" className={btn} onClick={() => setRows([...rows,
        { id: null, text: "", kind: "judgement", mine: false, flagged: true, outputs: [] }])}>{t("jobs.goal.add")}</button>
      <span className="flex-1" />
      <button type="button" className={btn} onClick={() => (started ? onClose() : onSend?.("/goal clear"))}>{t("jobs.goal.cancel")}</button>
      <button type="button" className={primary} disabled={blocked || !onSend} onClick={start}>
        <Target size={10} aria-hidden />{t("jobs.goal.start")}</button>
    </div>
    <p className="mt-1 text-[10px] text-muted-foreground">{t("jobs.goal.formHelp")}</p>
  </section>;
}

export default function GoalCard({ job, onSend }: { job: Job; onSend?: SendLine }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const g = job.goalState!;
  if (g.status === "not_started" || editing) {
    return <GoalForm job={job} started={g.status !== "not_started"} onSend={onSend} onClose={() => setEditing(false)} />;
  }
  const running = g.status === "active" && job.phase !== "finished";
  const tone = g.status === "complete" ? "border-success/50" : g.status === "active" ? "border-primary/40" : "border-warning/60";
  const n = String(g.round);
  const stop = () => (running ? void backgroundJobsApi.stop(job.jobId).catch(() => undefined) : onSend?.("/goal clear"));
  const resumable = ["blocked", "paused", "review", "budget_limited", "interrupted"].includes(g.status);
  const editable = ["active", "blocked", "paused", "review"].includes(g.status);
  const met = g.checks.filter((c) => c.status === "passed");
  return <section data-testid="goal-card" data-goal-card={job.jobId} aria-label={t("jobs.goal.kicker")}
    className={`my-2 rounded-xl border ${tone} bg-surface/60 px-4 py-3 text-xs`}>
    <header className="flex items-start gap-2">
      {running && <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-primary" aria-hidden />}
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{t("jobs.goal.kicker")}</div>
        <div className="break-words font-medium text-foreground">{objectiveOf(job.goal)}</div>
      </div>
      <span className="shrink-0 whitespace-nowrap rounded-full border border-border px-2 py-0.5 text-[10px]">{t(`jobs.goal.status.${g.status}`)}</span>
    </header>
    <div data-testid="goal-meta" className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
      <span className="font-medium text-foreground">{g.status === "active" ? t("jobs.goal.round", { n }) : t(`jobs.goal.roundAt.${g.status}`, { n })}</span>
      <span>{t("jobs.goal.metOf", { met: String(g.met), total: String(g.total) })}</span>
      {g.cap_usd != null && <span>{t("jobs.goal.spend", { spend: (g.spend_usd ?? 0).toFixed(2), cap: g.cap_usd.toFixed(2) })}</span>}
      {g.status === "active" && <span>{t(`jobs.goal.tier.${g.tier}`)}</span>}
    </div>
    {g.status === "budget_limited" ? <>
      <div className="mt-2 text-[10px] text-muted-foreground">{t("jobs.goal.done")}</div><Checks checks={met} />
      <div className="mt-2 text-[10px] text-muted-foreground">{t("jobs.goal.notYet")}</div>
      <Checks checks={g.checks.filter((c) => c.status !== "passed")} />
    </> : <><div className="mt-2 text-[10px] text-muted-foreground">{t("jobs.doneWhen")}</div><Checks checks={g.checks} /></>}
    {running && job.step && <p className="mt-2 text-muted-foreground">{t("jobs.now", { step: `${t("jobs.goal.round", { n })} · ${job.step}` })}</p>}
    {g.blocker && <p data-testid="goal-blocker" className={`mt-2 ${g.status === "blocked" ? "text-foreground" : "text-muted-foreground"}`}>
      {g.status === "blocked" ? t("jobs.goal.blockedBy", { why: t(`jobs.goal.blocker.${g.blocker.code}`) })
        : t(`jobs.goal.blocker.${g.blocker.code}`, { files: g.blocker.files.join(", ") })}</p>}
    {g.step && <p data-testid="goal-step" className="mt-1.5 rounded-md bg-foreground/5 px-2 py-1.5 text-[11.5px]">{t("jobs.goal.step", { step: g.step })}</p>}
    {g.missing_files.length > 0 && <p className="mt-2 text-warning">{t("jobs.goal.missing", { files: g.missing_files.join(", ") })}</p>}
    {g.unprotected && g.blocker?.code !== "unprotected" && <p className="mt-2 text-warning">{t("jobs.goal.blocker.unprotected")}</p>}
    {g.status !== "complete" && g.status !== "cleared" && <div className="mt-2 flex flex-wrap items-center gap-2">
      {resumable && <button type="button" className={primary} disabled={!onSend} onClick={() => onSend?.("/goal resume")}>
        <Play size={10} aria-hidden />{t("jobs.goal.resume")}</button>}
      {running && <button type="button" className={btn} disabled={!onSend} onClick={() => onSend?.("/goal pause")}>
        <Pause size={10} aria-hidden />{t("jobs.goal.pause")}</button>}
      {editable && <button type="button" className={btn} disabled={!onSend} onClick={() => setEditing(true)}>
        <Pencil size={10} aria-hidden />{t("jobs.goal.edit")}</button>}
      {running && <button type="button" className={btn} aria-expanded={noting} onClick={() => setNoting(!noting)}>
        <MessageSquare size={10} aria-hidden />{t("jobs.goal.note")}</button>}
      <button type="button" className={btn} onClick={stop}><Square size={10} aria-hidden />{t("jobs.goal.stop")}</button>
    </div>}
    {running && noting && <div className="mt-2 flex gap-1.5">
      <input type="text" className={input} aria-label={t("jobs.goal.noteLabel")} value={note} onChange={(e) => setNote(e.target.value)} />
      <button type="button" className={btn} disabled={!note.trim() || !onSend}
        onClick={() => { onSend?.(`/goal note ${note.trim()}`); setNote(""); setNoting(false); }}>{t("jobs.goal.sendNote")}</button>
    </div>}
    {(g.status === "blocked" || g.status === "budget_limited" || g.status === "interrupted") &&
      <p className="mt-1 text-[10px] text-muted-foreground">{t(`jobs.goal.hint.${g.status}`, { n })}</p>}
  </section>;
}

/** The composer chip while a goal is open: its objective and n of m; a click scrolls to its card. */
export function GoalChip() {
  const { t } = useTranslation();
  const jobs = useArslanStore((s) => s.jobs);
  const open = Object.values(jobs).find((j) => j.goalState && j.goalState.status !== "complete" && j.goalState.status !== "cleared");
  if (!open?.goalState) return null;
  return <button type="button" data-testid="goal-chip" title={t("jobs.goal.chip")}
    onClick={() => document.querySelector(`[data-goal-card="${CSS.escape(open.jobId)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" })}
    className="inline-flex max-w-full items-center gap-1.5 self-start rounded-xl border border-primary/35 bg-primary/10 px-2 py-[3px] text-[10px] leading-snug">
    <Target size={10} className="shrink-0 text-primary" aria-hidden />
    <span className="min-w-0 truncate font-semibold">{objectiveOf(open.goal)}</span>
    <span className="shrink-0 text-muted-foreground">{t("jobs.goal.chipCount", { met: String(open.goalState.met), total: String(open.goalState.total) })}</span>
  </button>;
}

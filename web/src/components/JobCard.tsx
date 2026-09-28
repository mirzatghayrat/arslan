import { useState } from "react";
import { Check, Circle, Loader2, Square, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { backgroundJobsApi } from "../api/tasks";
import type { JobCard as Job } from "../api/client.types";
import { useArslanStore } from "../stores/arslanStore";

// A background job's live card (0.1.42). The job runs on its own; this only
// shows the server's state: goal, the criteria Arslan drafted, the current
// step, and — once checked — the outcome. Stop is the one control.
export default function JobCard({ jobId }: { jobId: string }) {
  const { t } = useTranslation();
  const job = useArslanStore((s) => s.jobs[jobId]) as Job | undefined;
  const [stopError, setStopError] = useState(false);
  const [stopping, setStopping] = useState(false);
  if (!job) return null;
  const finished = job.phase === "finished";
  const tone = !finished ? "border-primary/40" : job.outcome === "done" ? "border-success/50"
    : job.outcome === "stopped" ? "border-border" : "border-warning/60";
  async function stop() {
    setStopping(true);
    try { await backgroundJobsApi.stop(jobId); setStopError(false); }
    catch { setStopError(true); }
    finally { setStopping(false); }
  }
  return <section data-testid="job-card" aria-label={t("jobs.title")}
    className={`my-2 rounded-xl border ${tone} bg-surface/60 px-4 py-3 text-xs`}>
    <header className="flex items-start gap-2">
      {finished ? null : <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-primary" aria-hidden />}
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{t("jobs.title")}</div>
        <div className="font-medium text-foreground">{job.goal}</div>
      </div>
      <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px]">
        {finished && job.outcome ? t(`jobs.outcome.${job.outcome}`) : job.phase === "queued" ? t("jobs.queued") : t("jobs.working")}
      </span>
    </header>
    {job.criteria.length > 0 && <div className="mt-2">
      <div className="text-[10px] text-muted-foreground">{t("jobs.doneWhen")}</div>
      <ul className="mt-1 space-y-0.5">{job.criteria.map((c) => <li key={c.id} className="flex items-start gap-1.5">
        {c.status === "passed" ? <Check size={12} className="mt-0.5 shrink-0 text-success" aria-hidden />
          : c.status === "failed" ? <X size={12} className="mt-0.5 shrink-0 text-danger" aria-hidden />
          : <Circle size={10} className="mt-1 shrink-0 text-muted-foreground" aria-hidden />}
        <span>{c.description} <span className="text-muted-foreground">· {t(`jobs.check.${c.status}`, { defaultValue: c.status })}</span></span>
      </li>)}</ul>
    </div>}
    {!finished && job.step && <p className="mt-2 text-muted-foreground">{t("jobs.now", { step: job.step })}</p>}
    {finished && job.detail && <p className="mt-2 text-muted-foreground">{job.detail}</p>}
    {!finished && <div className="mt-2 flex items-center gap-2">
      <button type="button" onClick={() => void stop()} disabled={stopping}
        className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] hover:bg-foreground/5 disabled:opacity-50">
        <Square size={10} aria-hidden />{t("jobs.stop")}</button>
      {stopError && <span role="status" className="text-[11px] text-muted-foreground">{t("jobs.stopFailed")}</span>}
    </div>}
  </section>;
}

/** Under a job's result message: which job it came from, and what the check concluded. */
export function JobResultLabel({ outcome }: { outcome?: Job["outcome"] }) {
  const { t } = useTranslation();
  return <p data-testid="job-result-label" className="mt-1 text-[10px] text-muted-foreground">
    {t("jobs.resultOf", { outcome: outcome ? t(`jobs.outcome.${outcome}`) : "—" })}
  </p>;
}

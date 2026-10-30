import { useTranslation } from "react-i18next";
import { Loader2, Square } from "lucide-react";
import { backgroundJobsApi } from "../../api/tasks";
import { HEADING } from "./FilesTab";

export type Job = { job_id: string; goal: string; phase: string; step?: string | null };

/**
 * Progress (WB1, v0.1.64): what runs for this conversation, each with a stop button — Task's
 * "working" list (0.1.58 §3). The Workbench polls the jobs, so the tab's count stays current
 * while another tab is selected. SUB's sub-session tree goes here later (SUB card).
 */
export default function ProgressTab({ jobs, reload }: { jobs: Job[]; reload: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto p-3" data-testid="progress-tab">
      {jobs.length === 0 ? <p className="text-[12.5px] text-muted-foreground" data-testid="progress-empty">{t("workbench.nothingRunning")}</p>
        : <section>
          <h3 className={HEADING}>{t("workbench.working")}</h3>
          <ul className="mt-2 space-y-2">{jobs.map((job) => <li key={job.job_id} className="rounded-lg border border-border p-2.5">
            <div className="flex items-start gap-2">
              <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-primary" aria-hidden />
              <div className="min-w-0 flex-1"><p className="break-words text-[12.5px] font-medium">{job.goal}</p>
                {job.step && <p className="mt-0.5 truncate text-[11.5px] text-muted-foreground">{job.step}</p>}</div>
              <button type="button" onClick={() => void backgroundJobsApi.stop(job.job_id).then(reload)}
                className="shrink-0 rounded-md bg-fill px-2 py-0.5 text-[11.5px] hover:bg-fill-strong">
                <Square size={10} className="mr-1 inline" aria-hidden />{t("workbench.stop")}</button>
            </div></li>)}</ul>
        </section>}
    </div>
  );
}

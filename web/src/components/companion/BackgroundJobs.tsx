import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { backgroundJobsApi } from "../../api/tasks";
import { useArslanStore } from "../../stores/arslanStore";

type Row = { job_id: string; conversation_id: string; goal: string; phase: string; step: string };

// Sidebar "In progress N" (0.1.42): background jobs across all conversations.
// Renders nothing when none run — a chat is not a task and gets no row here.
export default function BackgroundJobs({ onOpen }: { onOpen: (conversationId: string) => void }) {
  const { t } = useTranslation();
  const jobs = useArslanStore((s) => s.jobs);
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => backgroundJobsApi.list().then((body) => {
      if (alive) setRows(body.jobs.filter((job) => job.phase !== "finished"));
    }).catch(() => { /* the service may be restarting; keep the last rows */ });
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, [jobs]);
  if (rows.length === 0) return null;
  return <section aria-label={t("jobs.inProgress")} className="px-3 py-2">
    <div className="text-xs text-muted-foreground">{t("jobs.inProgress")} <span className="ml-1 tabular-nums text-foreground">{rows.length}</span></div>
    <div className="mt-1 max-h-32 space-y-0.5 overflow-y-auto">{rows.map((job) => <button key={job.job_id} title={job.goal}
      onClick={() => onOpen(job.conversation_id)} className="flex w-full items-start gap-2 rounded px-1 py-1.5 text-left text-xs hover:bg-primary/5">
      <Loader2 size={13} className="mt-0.5 shrink-0 animate-spin text-primary" aria-hidden />
      <span className="min-w-0"><span className="block truncate">{job.goal}</span>
        {job.step && <span className="block truncate text-[10px] text-muted-foreground">{job.step}</span>}</span>
    </button>)}</div>
  </section>;
}

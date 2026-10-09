import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FolderOpen, Loader2, Square } from "lucide-react";
import { backgroundJobsApi } from "../../api/tasks";
import { filesApi, type ConversationFile } from "../../api/files";
import { formatUiDateTime } from "../../lib/localeFormatting";
import { baseName } from "../../lib/fileKinds";
import { useArslanStore } from "../../stores/arslanStore";
import { useWorkbench } from "../../stores/workbenchStore";
import FileIcon from "./FileIcon";

type Job = { job_id: string; goal: string; phase: string; step?: string | null };
const POLL_MS = 5_000;
const heading = "text-[11px] font-semibold uppercase tracking-wider text-subtle-foreground";

/** "打开项目" from the workbench: the projects section opens that project's page (App listens). */
export const OPEN_PROJECT_EVENT = "arslan:open-project";

/**
 * 任务 (0.1.58 §3): what runs for this conversation (with 停止), the files THIS conversation
 * made (not the whole workspace's newest), its project, and its working folder.
 */
export default function TaskTab({ conversationId, files, home, project }: {
  conversationId: string; files: ConversationFile[]; home: string | null; project: { id: string; name: string } | null;
}) {
  const { t, i18n } = useTranslation();
  const storeJobs = useArslanStore((s) => s.jobs);
  const [jobs, setJobs] = useState<Job[]>([]);
  const openReader = useWorkbench((s) => s.openReader);
  const browse = useWorkbench((s) => s.browse);
  const load = useCallback(async () => {
    try {
      const r = await backgroundJobsApi.list(conversationId);
      setJobs(r.jobs.filter((j) => j.phase !== "finished") as Job[]);
    } catch { /* keep the last list */ }
  }, [conversationId]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [load, storeJobs]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-y-auto p-3" data-testid="task-tab">
      <section>
        <h3 className={heading}>{t("workbench.working")}</h3>
        {jobs.length === 0 ? <p className="mt-2 text-[12.5px] text-muted-foreground">{t("workbench.nothingRunning")}</p>
          : <ul className="mt-2 space-y-2">{jobs.map((job) => <li key={job.job_id} className="rounded-lg border border-border p-2.5">
            <div className="flex items-start gap-2">
              <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-primary" aria-hidden />
              <div className="min-w-0 flex-1"><p className="break-words text-[12.5px] font-medium">{job.goal}</p>
                {job.step && <p className="mt-0.5 truncate text-[11.5px] text-muted-foreground">{job.step}</p>}</div>
              <button type="button" onClick={() => void backgroundJobsApi.stop(job.job_id).then(load)}
                className="shrink-0 rounded-md bg-fill px-2 py-0.5 text-[11.5px] hover:bg-fill-strong">
                <Square size={10} className="mr-1 inline" aria-hidden />{t("workbench.stop")}</button>
            </div></li>)}</ul>}
      </section>
      <section>
        <h3 className={heading}>{t("workbench.convFiles")} <span className="font-mono">{files.length || ""}</span></h3>
        {files.length === 0 ? <p className="mt-2 text-[12.5px] text-muted-foreground">{t("workbench.noConvFiles")}</p>
          : <ul className="mt-1.5 space-y-0.5" data-testid="task-files">{files.map((f) => (
            <li key={`${f.run_id}-${f.filename}`}>
              <button type="button" onClick={() => openReader({ kind: "artifact", file: f })}
                className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-foreground/[0.04]">
                <FileIcon name={f.title} size={13} />
                <span className="min-w-0 flex-1 truncate text-[13px]">{baseName(f.title)}</span>
                <span className="shrink-0 text-[11px] text-subtle-foreground">
                  {f.created_at ? `${formatUiDateTime(f.created_at, i18n.language)} · ` : ""}{Math.max(1, Math.ceil(f.bytes / 1024))} KB</span>
              </button>
            </li>))}</ul>}
      </section>
      {project && <section>
        <h3 className={heading}>{t("workbench.project")}</h3>
        <button type="button" className="mt-2 text-left text-[13px] font-medium hover:underline"
          onClick={() => window.dispatchEvent(new CustomEvent(OPEN_PROJECT_EVENT, { detail: project.id }))}>
          {project.name} · {t("workbench.openProject")} ›</button>
      </section>}
      {home && <section>
        <h3 className={heading}>{t("workbench.folder")}</h3>
        <div className="mt-2 flex items-center gap-2 text-[12.5px]">
          <FolderOpen size={14} className="text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{home}</span>
          <button type="button" onClick={() => browse(home)} className="text-subtle-foreground hover:text-foreground">{t("workbench.browse")} ›</button>
          <button type="button" onClick={() => void filesApi.reveal(home)} className="text-subtle-foreground hover:text-foreground"
            aria-label={t("workbench.reveal")}><FolderOpen size={13} /></button>
        </div>
      </section>}
    </div>
  );
}

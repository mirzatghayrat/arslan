import { useCallback, useEffect, useState } from "react";
import { FileText, FolderOpen, Loader2, Square, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { backgroundJobsApi } from "../../api/tasks";
import { workspaceApi, type WorkspaceInfo } from "../../api/workspace";
import { formatUiDateTime } from "../../lib/localeFormatting";
import { useArslanStore } from "../../stores/arslanStore";

type Job = { job_id: string; goal: string; phase: string; step?: string | null };
const POLL_MS = 5_000;
const home = (path: string) => path.replace(/^\/Users\/[^/]+/, "~");

/**
 * The panel beside a conversation (0.1.48). It replaced the expert-era "diagnostics engine"
 * rail (spawn pipeline, invite spawns, level bars), which had nothing to show once there was
 * one Arslan. What is useful next to a conversation is its working context: what is running
 * for it, what Arslan saved, and where.
 */
export default function ContextPanel({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const storeJobs = useArslanStore((s) => s.jobs);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [folder, setFolder] = useState<WorkspaceInfo | null>(null);
  const [folderError, setFolderError] = useState(false);

  const load = useCallback(async () => {
    const [j, w] = await Promise.allSettled([backgroundJobsApi.list(conversationId), workspaceApi.get()]);
    if (j.status === "fulfilled") setJobs(j.value.jobs.filter((job) => job.phase !== "finished") as Job[]);
    if (w.status === "fulfilled") { setFolder(w.value); setFolderError(false); } else setFolderError(true);
  }, [conversationId]);
  useEffect(() => {
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [load, storeJobs]);

  const heading = "text-[11px] font-medium uppercase tracking-wider text-muted-foreground";
  return <aside data-testid="context-panel" aria-label={t("panel.title")}
    className="absolute right-0 top-0 z-40 flex h-full w-72 shrink-0 flex-col border-l border-border bg-sidebar shadow-xl xl:relative xl:shadow-none">
    <header className="flex items-center justify-between border-b border-border/50 px-4 py-3">
      <h2 className="text-sm font-medium">{t("panel.title")}</h2>
      <button onClick={onClose} aria-label={t("panel.close")} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
    </header>
    <div className="flex-1 space-y-6 overflow-y-auto px-4 py-4 text-sm">
      <section aria-labelledby="panel-working">
        <h3 id="panel-working" className={heading}>{t("panel.working")}</h3>
        {jobs.length === 0 ? <p className="mt-2 text-xs text-muted-foreground">{t("panel.nothingRunning")}</p>
          : <ul className="mt-2 space-y-2">{jobs.map((job) => <li key={job.job_id} className="rounded-lg border border-border/60 p-2.5">
            <div className="flex items-start gap-2">
              <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-primary" aria-hidden />
              <div className="min-w-0 flex-1"><p className="break-words text-xs">{job.goal}</p>
                {job.step && <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{job.step}</p>}</div>
              <button onClick={() => void backgroundJobsApi.stop(job.job_id).then(load)} aria-label={t("panel.stop")}
                className="shrink-0 rounded p-1 text-muted-foreground hover:bg-foreground/5 hover:text-foreground"><Square size={12} /></button>
            </div></li>)}</ul>}
      </section>
      <section aria-labelledby="panel-files">
        <h3 id="panel-files" className={heading}>{t("panel.files")}</h3>
        {folderError ? <p role="alert" className="mt-2 text-xs text-muted-foreground">{t("panel.unavailable")}</p>
          : !folder?.recent.length ? <p className="mt-2 text-xs text-muted-foreground">{t("panel.noFiles")}</p>
          : <ul className="mt-2 space-y-0.5">{folder.recent.map((file) => <li key={file.path} className="group flex items-center gap-2 rounded px-1.5 py-1 hover:bg-foreground/5">
            <FileText size={13} className="shrink-0 text-muted-foreground" aria-hidden />
            <button onClick={() => void workspaceApi.open(file.path)} title={file.path} className="min-w-0 flex-1 text-left">
              <span className="block truncate text-xs">{file.name}</span>
              <span className="block text-[10px] text-muted-foreground">{formatUiDateTime(file.modified, i18n.language)}</span>
            </button>
            <button onClick={() => void workspaceApi.reveal(file.path)} aria-label={`${t("panel.reveal")}: ${file.name}`}
              className="shrink-0 rounded p-1 text-muted-foreground opacity-0 hover:text-foreground group-hover:opacity-100 focus:opacity-100"><FolderOpen size={12} /></button>
          </li>)}</ul>}
      </section>
      {folder && <section aria-labelledby="panel-folder">
        <h3 id="panel-folder" className={heading}>{t("panel.folder")}</h3>
        <p className="mt-2 break-all text-xs">{home(folder.path)}</p>
        <p className="text-[11px] text-muted-foreground">{t(folder.is_default ? "panel.ownFolder" : "panel.chosenFolder")}</p>
        <button onClick={() => void workspaceApi.reveal()} className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-foreground/5">
          <FolderOpen size={12} />{t("panel.openFolder")}</button>
      </section>}
    </div>
  </aside>;
}

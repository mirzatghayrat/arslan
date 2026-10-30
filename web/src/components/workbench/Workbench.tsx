import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { MoreHorizontal, X } from "lucide-react";
import { api } from "../../api/client";
import { filesApi, type ConversationFile } from "../../api/files";
import { backgroundJobsApi } from "../../api/tasks";
import { useDismissable } from "../../hooks/useDismissable";
import { OPEN_ARTIFACT, validArtifact } from "../../lib/workDock";
import { useArslanStore } from "../../stores/arslanStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { READER_WIDTH, useWorkbench, type WorkbenchTab } from "../../stores/workbenchStore";
import WorkDock from "../WorkDock";
import FilesTab from "./FilesTab";
import ProgressTab, { type Job } from "./ProgressTab";
import Reader from "./Reader";

// WB1 (user, 2026-10-30): a fixed row, always shown. The ids stay; Working folder's label is
// workbench.folder (the user may still pick "Project folder"). Later tabs come from "+" (SIDE, SUB).
const TABS: WorkbenchTab[] = ["files", "progress", "browser"];
const LABEL: Record<WorkbenchTab, string> = { files: "workbench.folder", progress: "workbench.progress", browser: "workbench.browser" };
const REFRESH_MS = 10_000;
const JOBS_MS = 5_000;

function MoreMenu({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, () => setOpen(false));
  const settings = useSettingsStore((s) => s.settings);
  const awake = settings?.keep_awake_enabled ?? true;
  return (
    <span className="relative">
      <button ref={anchorRef} type="button" aria-label={t("workbench.more")} aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((v) => !v)} className="rounded-md p-1.5 text-muted-foreground hover:bg-foreground/5" data-testid="workbench-more">
        <MoreHorizontal size={16} /></button>
      {open && <div ref={floatingRef} role="menu" className="absolute right-0 top-full z-40 mt-1 w-64 rounded-xl border border-border bg-background p-1.5 shadow-lg">
        <label className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-[12.5px]">
          <span>{t("workbench.keepAwake")}</span>
          <input type="checkbox" className="kit-switch" checked={awake} data-testid="workbench-keep-awake"
            onChange={(e) => {
              const next = e.target.checked;
              void api.updateSettings({ keep_awake_enabled: next }).then((saved) => useSettingsStore.getState().setSettings(saved));
            }} />
        </label>
        <button type="button" role="menuitem" onClick={() => { setOpen(false); onClose(); }}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] text-muted-foreground hover:bg-foreground/5">
          <X size={13} />{t("workbench.close")}</button>
      </div>}
    </span>
  );
}

/**
 * The right-hand workbench (0.1.58 §3, decision 7; WB1 in v0.1.64): one panel with a fixed row —
 * Working folder (the conversation's folder, and for now the files it made), Progress (what runs,
 * with stop) and Browser (the user's URL reader) — and the reader sliding over them. Resizable from
 * its left edge; the reader widens it while open. It never opens by itself.
 */
export default function Workbench({ conversationId, taskId, temporary }: {
  conversationId: string; taskId: string | null; temporary: boolean;
}) {
  const { t } = useTranslation();
  const { open, tab, reader, width, show, close, openReader, closeReader, setWidth } = useWorkbench();
  const items = useArslanStore((s) => s.items);
  const [files, setFiles] = useState<ConversationFile[]>([]);
  const [home, setHome] = useState<{ path: string | null; project: { id: string; name: string } | null }>({ path: null, project: null });

  // A file card or ArtifactDownloads "preview" opens the delivered file in the reader.
  useEffect(() => {
    const onOpen = (e: Event) => { const file = (e as CustomEvent).detail; if (validArtifact(file)) openReader({ kind: "artifact", file }); };
    window.addEventListener(OPEN_ARTIFACT, onOpen);
    return () => window.removeEventListener(OPEN_ARTIFACT, onOpen);
  }, [openReader]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    filesApi.home(conversationId).then((h) => { if (alive) setHome(h); }).catch(() => {});
    const load = () => filesApi.conversationFiles(conversationId).then((r) => { if (alive) setFiles(r.files); }).catch(() => {});
    void load();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [open, conversationId, items.length]);

  // The job poll lives here (it was Task's), so Progress shows its count while another tab is selected.
  const storeJobs = useArslanStore((s) => s.jobs);
  const [jobs, setJobs] = useState<Job[]>([]);
  const loadJobs = useCallback(async () => {
    try {
      const r = await backgroundJobsApi.list(conversationId);
      setJobs(r.jobs.filter((j) => j.phase !== "finished") as Job[]);
    } catch { /* keep the last list */ }
  }, [conversationId]);
  useEffect(() => {
    if (!open) return;
    void loadJobs();
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void loadJobs(); }, JOBS_MS);
    return () => clearInterval(timer);
  }, [open, loadJobs, storeJobs]);

  const touched = useMemo(() => new Set(files.map((f) => f.title)), [files]);
  if (!open) return null;
  const shownWidth = reader ? Math.max(width, READER_WIDTH) : width;
  return (
    <aside aria-label={t("workbench.toggle")} data-testid="workbench" style={{ width: shownWidth, maxWidth: "60vw" }}
      className="relative z-20 flex h-full min-w-0 shrink-0 flex-col border-l border-border bg-sidebar">
      {/* WB1: the panel's 1 px border is the line; this 8 px strip is only the hit area. Hover darkens the
          line a little; only a keyboard focus shows a ring, so a mouse drag never leaves it lit. */}
      <div role="separator" aria-orientation="vertical" tabIndex={0} aria-label={t("dock.resize")}
        className="absolute -left-1 top-0 z-30 h-full w-2 cursor-col-resize touch-none outline-none after:absolute after:left-1 after:top-0 after:h-full after:w-px after:content-[''] hover:after:bg-border-strong focus-visible:ring-2 focus-visible:ring-ring"
        onKeyDown={(e) => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); setWidth(width + (e.key === "ArrowLeft" ? 20 : -20)); } }}
        onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
        onPointerMove={(e) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) setWidth(window.innerWidth - e.clientX); }}
        onPointerUp={(e) => e.currentTarget.releasePointerCapture(e.pointerId)} />
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="inline-flex rounded-lg bg-fill p-0.5 text-[12.5px]" role="tablist">
          {TABS.map((k) => <button key={k} type="button" role="tab" aria-selected={tab === k && !reader} data-testid={`workbench-tab-${k}`}
            onClick={() => show(k)} className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 ${tab === k && !reader ? "bg-background font-semibold shadow-sm" : "text-muted-foreground"}`}>
            {t(LABEL[k])}
            {k === "progress" && jobs.length > 0 && <span data-testid="workbench-progress-count"
              className="min-w-4 rounded-full bg-info/15 px-1 text-[10px] font-semibold leading-4 text-info">{jobs.length}</span>}</button>)}
        </span>
        <MoreMenu onClose={close} />
      </header>
      <div className="relative min-h-0 flex-1">
        <div hidden={!!reader} className="h-full">
          {tab === "files" && <FilesTab home={home.path} touched={touched} files={files} />}
          {tab === "progress" && <ProgressTab jobs={jobs} reload={() => void loadJobs()} />}
          {tab === "browser" && <WorkDock embedded open onOpen={() => {}} onClose={close} conversationId={conversationId} taskId={taskId} temporary={temporary} />}
        </div>
        {/* keyed per file: a new file starts from "reading…", never from the last file's view */}
        {reader && <div className="absolute inset-0 bg-sidebar"><Reader key={reader.kind === "path" ? reader.path
          : `${reader.file.run_id}/${reader.file.filename}`} source={reader} onBack={closeReader} /></div>}
      </div>
    </aside>
  );
}

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, FolderOpen, MoreHorizontal, Search } from "lucide-react";
import { filesApi, type ConversationFile, type Folder, type FolderEntry } from "../../api/files";
import { useDismissable } from "../../hooks/useDismissable";
import { formatUiDateTime } from "../../lib/localeFormatting";
import { baseName } from "../../lib/fileKinds";
import { useWorkbench } from "../../stores/workbenchStore";
import FileIcon from "./FileIcon";
import { COMPOSER_INSERT_EVENT } from "./Reader";

/** WB1: section headings are small, grey and sentence case (no all-caps with letter spacing). */
export const HEADING = "text-[11.5px] font-medium text-muted-foreground";

function RowMenu({ entry, onRead }: { entry: FolderEntry; onRead: () => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(open, () => setOpen(false));
  const item = "block w-full rounded px-2 py-1.5 text-left text-[12px] hover:bg-foreground/5";
  const run = (fn: () => void) => () => { setOpen(false); fn(); };
  return (
    <span className="relative shrink-0">
      <button ref={anchorRef} type="button" aria-label={t("workbench.more")} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }} data-testid={`files-menu-${entry.name}`}
        className="rounded p-1 text-subtle-foreground opacity-0 hover:bg-foreground/5 focus:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100">
        <MoreHorizontal size={14} />
      </button>
      {open && <div ref={floatingRef} role="menu" onClick={(e) => e.stopPropagation()}
        className="absolute right-0 top-full z-30 mt-1 min-w-44 rounded-md border border-border bg-background p-1 shadow-md">
        {!entry.is_dir && <button type="button" role="menuitem" className={item} onClick={run(onRead)}>{t("workbench.read")}</button>}
        <button type="button" role="menuitem" className={item} onClick={run(() => void filesApi.open(entry.path))}>{t("workbench.open")}</button>
        <button type="button" role="menuitem" className={item} onClick={run(() => void filesApi.reveal(entry.path))}>{t("workbench.reveal")}</button>
        <button type="button" role="menuitem" className={item} onClick={run(() => void navigator.clipboard?.writeText(entry.path))}>{t("workbench.copyPath")}</button>
        <button type="button" role="menuitem" className={item} data-testid={`files-add-${entry.name}`}
          onClick={run(() => window.dispatchEvent(new CustomEvent(COMPOSER_INSERT_EVENT, { detail: `\`${entry.path}\`` })))}>{t("workbench.addToChat")}</button>
      </div>}
    </span>
  );
}

/**
 * Working folder (0.1.58 §3's 文件, WB1): the conversation's folder — its project's folder, else
 * Arslan's own — with "Show in Finder" in its header bar, browsed in Arslan: breadcrumbs, a filter,
 * folders first; a folder opens, a file opens in the reader; files this conversation produced carry
 * a dot. Hidden files are never listed. The files this conversation made are listed on top (from
 * the old Task tab) until WB1-2 moves them to Overview's Deliverables.
 */
export default function FilesTab({ home, touched, files }: { home: string | null; touched: Set<string>; files: ConversationFile[] }) {
  const { t, i18n } = useTranslation();
  const folder = useWorkbench((s) => s.folder) ?? home;
  const browse = useWorkbench((s) => s.browse);
  const openReader = useWorkbench((s) => s.openReader);
  const [data, setData] = useState<Folder | null>(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState("");
  const [extra, setExtra] = useState<FolderEntry[]>([]);

  useEffect(() => {
    if (!folder) return;
    let alive = true;
    setFailed(false); setExtra([]); setFilter("");
    filesApi.list(folder).then((f) => { if (alive) setData(f); }).catch(() => { if (alive) { setData(null); setFailed(true); } });
    return () => { alive = false; };
  }, [folder]);

  const entries = useMemo(() => {
    const all = [...(data?.entries ?? []), ...extra];
    const q = filter.trim().toLowerCase();
    return q ? all.filter((e) => e.name.toLowerCase().includes(q)) : all;
  }, [data, extra, filter]);
  const isTouched = (e: FolderEntry) => !e.is_dir && [...touched].some((p) => e.path.endsWith(`/${p}`) || e.path === p);

  if (!folder) return <p className="p-4 text-[13px] text-muted-foreground">{t("workbench.unreadable")}</p>;
  return (
    <div className="flex h-full min-h-0 flex-col gap-2 p-3" data-testid="files-tab">
      <div className="flex items-center gap-2 border-b border-border pb-2 text-[12.5px]" data-testid="files-folderbar">
        <FolderOpen size={14} className="shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate font-mono text-[12px]" title={folder}>{folder}</span>
        <button type="button" onClick={() => void filesApi.reveal(folder)} data-testid="files-reveal"
          className="shrink-0 rounded-md px-1.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-foreground/5 hover:text-foreground">
          {t("workbench.reveal")}</button>
      </div>
      {files.length > 0 && <section>
        <h3 className={HEADING}>{t("workbench.convFiles")}</h3>
        <ul className="mt-1 space-y-0.5" data-testid="conv-files">{files.map((f) => (
          <li key={`${f.run_id}-${f.filename}`}>
            <button type="button" onClick={() => openReader({ kind: "artifact", file: f })}
              className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-foreground/[0.04]">
              <FileIcon name={f.title} size={13} />
              <span className="min-w-0 flex-1 truncate text-[13px]">{baseName(f.title)}</span>
              <span className="shrink-0 text-[11px] text-subtle-foreground">
                {f.created_at ? `${formatUiDateTime(f.created_at, i18n.language)} · ` : ""}{Math.max(1, Math.ceil(f.bytes / 1024))} KB</span>
            </button>
          </li>))}</ul>
      </section>}
      <nav className="flex flex-wrap items-center gap-1 text-[12px] text-muted-foreground" data-testid="files-crumbs">
        {(data?.crumbs ?? []).map((c, i, all) => <span key={c.path} className="flex items-center gap-1">
          <button type="button" onClick={() => browse(c.path)}
            className={i === all.length - 1 ? "font-semibold text-foreground" : "hover:text-foreground"}>{c.name}</button>
          {i < all.length - 1 && <ChevronRight size={11} />}
        </span>)}
      </nav>
      <label className="flex items-center gap-2 rounded-lg bg-fill px-2.5 py-1.5 text-[12.5px]">
        <Search size={13} className="text-subtle-foreground" />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("workbench.filter")}
          className="min-w-0 flex-1 bg-transparent outline-none" data-testid="files-filter" />
      </label>
      {failed && <p role="alert" className="text-[12.5px] text-muted-foreground">{t("workbench.unreadable")}</p>}
      {data && !entries.length && !failed && <p className="text-[12.5px] text-muted-foreground">{t("workbench.empty")}</p>}
      <ul className="min-h-0 flex-1 overflow-y-auto" data-testid="files-list">
        {entries.map((e) => (
          <li key={e.path} className="group flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-foreground/[0.04]" data-testid={`files-row-${e.name}`}>
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${isTouched(e) ? "bg-info" : "bg-transparent"}`}
              data-touched={isTouched(e) || undefined} aria-hidden />
            <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left"
              onClick={() => (e.is_dir ? browse(e.path) : openReader({ kind: "path", path: e.path }))}>
              <FileIcon name={e.name} folder={e.is_dir} size={13} />
              <span className="min-w-0 flex-1 truncate text-[13px]">{e.name}</span>
              <span className="shrink-0 text-[11px] text-subtle-foreground">
                {e.bytes != null ? `${Math.max(1, Math.ceil(e.bytes / 1024))} KB · ` : ""}{formatUiDateTime(e.modified, i18n.language)}</span>
            </button>
            <RowMenu entry={e} onRead={() => openReader({ kind: "path", path: e.path })} />
          </li>
        ))}
      </ul>
      {data?.more && <button type="button" className="self-start text-[12px] text-subtle-foreground hover:text-foreground"
        onClick={() => void filesApi.list(folder, (data.entries.length + extra.length)).then((f) => setExtra((x) => [...x, ...f.entries]))}>
        {t("workbench.showMore")}</button>}
      <p className="flex items-center gap-1.5 text-[11px] text-subtle-foreground">
        <span className="h-1.5 w-1.5 rounded-full bg-info" aria-hidden />{t("workbench.touched")}</p>
    </div>
  );
}

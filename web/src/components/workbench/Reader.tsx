import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, Copy, Download, ExternalLink, FolderOpen, MessageSquarePlus } from "lucide-react";
import { api } from "../../api/client";
import { filesApi, type TableSheet } from "../../api/files";
import { baseName, dirName, kindOf, mimeOf, parseDelimited } from "../../lib/fileKinds";
import type { ReaderSource } from "../../stores/workbenchStore";
import Markdown from "../Markdown";
import FileIcon from "./FileIcon";

export const TEXT_CAP = 100_000;
export const TABLE_ROWS = 1000;
/** "加进对话": the composer of the open conversation appends this text (OrchestratorChat listens). */
export const COMPOSER_INSERT_EVENT = "arslan:composer-insert";

type Loaded =
  | { kind: "text"; text: string; cut: boolean }
  | { kind: "url"; url: string }
  | { kind: "table"; sheets: TableSheet[] }
  | { kind: "html"; html: string }
  | { kind: "none" };

function errorKey(cause: unknown): string {
  const code = (cause as { detail?: { code?: string } })?.detail?.code;
  return code === "outside" ? "workbench.outside" : code === "hidden" ? "workbench.hidden"
    : code === "missing" ? "workbench.missing" : code === "too_big" ? "workbench.tooBig" : "workbench.failed";
}

const decode = (buf: ArrayBuffer) => new TextDecoder("utf-8", { fatal: false }).decode(buf);

/**
 * The reader (0.1.58 §2): a file shown the way it is meant to be read — Markdown rendered,
 * HTML drawn in a sandbox="" frame (no scripts, no same-origin: the HX-2 rule; "在浏览器打开"
 * runs it on purpose), PDF in WebKit's own viewer with a page-image fallback, images, players,
 * tables for csv/xlsx, Word through macOS's textutil, text with line numbers. Read-only.
 */
export default function Reader({ source, onBack }: { source: ReaderSource; onBack: () => void }) {
  const { t } = useTranslation();
  const name = source.kind === "artifact" ? baseName(source.file.title) : baseName(source.path);
  const path = source.kind === "path" ? source.path : null;
  const kind = kindOf(name);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bytes, setBytes] = useState<number | null>(source.kind === "artifact" ? source.file.bytes : null);
  const [mode, setMode] = useState<"rendered" | "source">("rendered");
  const [wrap, setWrap] = useState(true);
  const [fit, setFit] = useState(true);
  const [pdfImages, setPdfImages] = useState<string[] | null>(null);
  const [sheet, setSheet] = useState(0);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let url: string | null = null;
    setLoaded(null); setError(null); setPdfImages(null); setMode("rendered"); setSheet(0);
    void (async () => {
      if (path && kind === "xlsx") { const r = await filesApi.table(path); if (alive) setLoaded({ kind: "table", sheets: r.sheets }); return; }
      if (path && kind === "doc") { const r = await filesApi.html(path); if (alive) setLoaded({ kind: "html", html: r.html }); return; }
      const blob = source.kind === "artifact"
        ? await api.downloadRunArtifact(source.file.run_id, source.file.filename)
        : await filesApi.read(source.path);
      const buf = await blob.arrayBuffer();
      if (!alive) return;
      setBytes(buf.byteLength);
      if (kind === "markdown" || kind === "text" || kind === "html" || kind === "table") {
        let text = decode(buf);
        if (kind === "table") {
          const parsed = parseDelimited(text, name.toLowerCase().endsWith(".tsv") ? "\t" : ",", TABLE_ROWS);
          setLoaded({ kind: "table", sheets: [{ name, rows: parsed.rows, truncated: parsed.truncated }] });
          return;
        }
        if (name.toLowerCase().endsWith(".json")) { try { text = JSON.stringify(JSON.parse(text), null, 2); } catch { /* keep as is */ } }
        setLoaded({ kind: "text", text: text.slice(0, TEXT_CAP), cut: text.length > TEXT_CAP });
      } else if (kind === "image" || kind === "video" || kind === "audio" || kind === "pdf") {
        url = URL.createObjectURL(new Blob([buf], { type: mimeOf(name) }));
        setLoaded({ kind: "url", url });
      } else if (kind === "doc" || kind === "xlsx") {
        // A delivered snapshot has no path to convert: its text, as the attachment reader gets it.
        const extracted = await api.extractAttachmentFile(new File([buf], name));
        if (alive) setLoaded({ kind: "text", text: extracted.text.slice(0, TEXT_CAP), cut: extracted.truncated });
      } else setLoaded({ kind: "none" });
    })().catch((cause) => { if (alive) setError(errorKey(cause)); });
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [source, path, kind, name]);

  async function showPdfImages() {
    if (!path) return;
    const first = await filesApi.pdfPage(path, 0);
    const urls = [URL.createObjectURL(first.image)];
    setPdfImages([...urls]);
    for (let i = 1; i < Math.min(first.pages, 30); i++) {
      urls.push(URL.createObjectURL((await filesApi.pdfPage(path, i)).image));
      setPdfImages([...urls]);
    }
  }

  const act = "rounded-md p-1.5 text-muted-foreground hover:bg-foreground/5 hover:text-foreground";
  const shownPath: string | null = path ?? (source.kind === "artifact" ? source.file.title : null);
  async function download() {
    if (source.kind !== "artifact") return;
    const blob = await api.downloadRunArtifact(source.file.run_id, source.file.filename);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const lines = useMemo(() => (loaded?.kind === "text" ? loaded.text.split("\n") : []), [loaded]);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="reader" data-kind={kind}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <button type="button" onClick={onBack} aria-label={t("workbench.back")} className={act} data-testid="reader-back"><ChevronLeft size={16} /></button>
        <FileIcon name={name} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold">{name}</div>
          <div className="truncate text-[11px] text-subtle-foreground">
            {bytes != null ? `${Math.max(1, Math.ceil(bytes / 1024))} KB · ` : ""}{shownPath ? dirName(String(shownPath)) : ""}</div>
        </div>
        {(kind === "markdown" || kind === "html") && loaded?.kind === "text" && (
          <span className="inline-flex rounded-lg bg-fill p-0.5 text-[11.5px]" role="group">
            {(["rendered", "source"] as const).map((m) => <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}
              data-testid={`reader-mode-${m}`} className={`rounded-md px-2 py-0.5 ${mode === m ? "bg-background font-semibold shadow-sm" : "text-muted-foreground"}`}>
              {t(`workbench.${m}`)}</button>)}
          </span>
        )}
        {path && <button type="button" className={act} title={t("workbench.open")} aria-label={t("workbench.open")}
          onClick={() => void filesApi.open(path)} data-testid="reader-open"><ExternalLink size={15} /></button>}
        {path && <button type="button" className={act} title={t("workbench.reveal")} aria-label={t("workbench.reveal")}
          onClick={() => void filesApi.reveal(path)}><FolderOpen size={15} /></button>}
        {shownPath && <button type="button" className={act} title={t("workbench.copyPath")} aria-label={t("workbench.copyPath")}
          onClick={() => { void navigator.clipboard?.writeText(String(shownPath)); setNote(t("workbench.copied")); }}><Copy size={15} /></button>}
        {path && <button type="button" className={act} title={t("workbench.addToChat")} aria-label={t("workbench.addToChat")} data-testid="reader-add"
          onClick={() => window.dispatchEvent(new CustomEvent(COMPOSER_INSERT_EVENT, { detail: `\`${path}\`` }))}><MessageSquarePlus size={15} /></button>}
        {source.kind === "artifact" && <button type="button" className={act} title={t("workbench.download")} aria-label={t("workbench.download")}
          onClick={() => void download()}><Download size={15} /></button>}
      </div>
      {note && <div role="status" className="px-3 pt-1 text-[11px] text-subtle-foreground">{note}</div>}
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {error && <p role="alert" className="text-[13px] text-muted-foreground" data-testid="reader-error">{t(error)}</p>}
        {!error && !loaded && <p role="status" className="text-[13px] text-subtle-foreground">{t("workbench.loading")}</p>}
        {loaded?.kind === "text" && kind === "markdown" && mode === "rendered" && (
          <div className="rounded-xl border border-border bg-background px-5 py-4" data-testid="reader-markdown"><Markdown>{loaded.text}</Markdown></div>)}
        {loaded?.kind === "text" && kind === "html" && mode === "rendered" && (<>
          {/* 🔒 sandbox="" — no scripts, no same-origin: a file's HTML can never reach Arslan's page. */}
          <iframe title={name} sandbox="" srcDoc={loaded.text} className="h-[70vh] w-full rounded-lg border border-border bg-white" data-testid="reader-html" />
          {path && <button type="button" onClick={() => void filesApi.open(path)} className="mt-2 text-[12px] text-subtle-foreground hover:text-foreground">
            {t("workbench.openInBrowser")}</button>}
        </>)}
        {loaded?.kind === "text" && !(mode === "rendered" && (kind === "markdown" || kind === "html")) && (<>
          <div className="mb-1 flex justify-end"><label className="flex items-center gap-1 text-[11px] text-subtle-foreground">
            <input type="checkbox" checked={wrap} onChange={(e) => setWrap(e.target.checked)} />{t("workbench.wrap")}</label></div>
          <div className="grid grid-cols-[auto_1fr] gap-x-3 font-mono text-[11.5px] leading-[1.55]" data-testid="reader-text">
            {lines.map((line, i) => [<span key={`n${i}`} className="select-none text-right text-subtle-foreground">{i + 1}</span>,
              <span key={`l${i}`} className={wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre"}>{line || " "}</span>])}
          </div>
          {loaded.cut && <p className="mt-2 text-[11.5px] text-subtle-foreground">{t("workbench.textCut")}</p>}
        </>)}
        {loaded?.kind === "html" && <iframe title={name} sandbox="" srcDoc={loaded.html}
          className="h-[70vh] w-full rounded-lg border border-border bg-white" data-testid="reader-doc" />}
        {loaded?.kind === "table" && (() => {
          const s = loaded.sheets[sheet] ?? loaded.sheets[0];
          if (!s) return null;
          return <div data-testid="reader-table">
            {loaded.sheets.length > 1 && <div className="mb-2 flex gap-1">{loaded.sheets.map((x, i) =>
              <button key={i} type="button" onClick={() => setSheet(i)} className={`rounded-md px-2 py-0.5 text-[12px] ${i === sheet ? "bg-fill font-semibold" : "text-muted-foreground"}`}>{x.name}</button>)}</div>}
            <div className="overflow-auto rounded-lg border border-border">
              <table className="w-full border-collapse text-[12px]"><tbody>
                {s.rows.map((row, r) => <tr key={r} className={r === 0 ? "sticky top-0 bg-fill font-semibold" : "border-t border-border"}>
                  {row.map((cell, c) => <td key={c} className="whitespace-nowrap px-2 py-1">{cell}</td>)}</tr>)}
              </tbody></table>
            </div>
            {s.truncated && <p className="mt-2 text-[11.5px] text-subtle-foreground">{t("workbench.rowsCut", { count: TABLE_ROWS })}</p>}
          </div>;
        })()}
        {loaded?.kind === "url" && kind === "image" && (<>
          <div className="mb-1 flex justify-end gap-2 text-[11px]">
            <button type="button" onClick={() => setFit(true)} className={fit ? "font-semibold" : "text-subtle-foreground"}>{t("workbench.fit")}</button>
            <button type="button" onClick={() => setFit(false)} className={!fit ? "font-semibold" : "text-subtle-foreground"}>{t("workbench.actual")}</button></div>
          <img src={loaded.url} alt={name} className={fit ? "max-w-full" : "max-w-none"} data-testid="reader-image" /></>)}
        {loaded?.kind === "url" && kind === "video" && <video controls preload="metadata" src={loaded.url} className="w-full" data-testid="reader-video" />}
        {loaded?.kind === "url" && kind === "audio" && <audio controls preload="metadata" src={loaded.url} className="w-full" data-testid="reader-audio" />}
        {loaded?.kind === "url" && kind === "pdf" && (pdfImages ? (
          <div className="flex flex-col gap-2" data-testid="reader-pdf-images">{pdfImages.map((u, i) => <img key={i} src={u} alt={`${name} ${i + 1}`} className="w-full rounded border border-border" />)}</div>
        ) : (<>
          <iframe title={name} src={loaded.url} className="h-[75vh] w-full rounded-lg border border-border" data-testid="reader-pdf" />
          {path && <button type="button" onClick={() => void showPdfImages()} className="mt-2 text-[12px] text-subtle-foreground hover:text-foreground"
            data-testid="reader-pdf-as-images">{t("workbench.asImages")}</button>}
        </>))}
        {loaded?.kind === "none" && <div className="flex flex-col gap-2 text-[13px] text-muted-foreground" data-testid="reader-none">
          <p>{t("workbench.noPreview")}</p>
          {path && <button type="button" onClick={() => void filesApi.open(path)} className="self-start rounded-lg border border-border px-3 py-1.5 text-foreground">{t("workbench.open")}</button>}
          {source.kind === "artifact" && <button type="button" onClick={() => void download()} className="self-start rounded-lg border border-border px-3 py-1.5 text-foreground">{t("workbench.download")}</button>}
        </div>}
      </div>
    </div>
  );
}

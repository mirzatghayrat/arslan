import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, RefreshCw, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import { browserApi, type ReaderAction, type ReaderFrame } from "../api/browser";

const button = "rounded-md border border-border p-2 hover:bg-surface disabled:opacity-40";

export default function BrowserReader({ conversationId, taskId, onTitle }: {
  conversationId: string; taskId: string | null; onTitle: (title: string) => void;
}) {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const [frame, setFrame] = useState<ReaderFrame | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const session = useRef<string | null>(null);
  const generation = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; generation.current++; if (session.current) void browserApi.closeReader(session.current).catch(() => {}); };
  }, []);

  async function stop() {
    generation.current++;
    const id = session.current; session.current = null;
    setBusy(false); setFrame(null);
    if (id) await browserApi.closeReader(id).catch(() => setError("dock.error"));
  }
  async function act(action: ReaderAction) {
    if (busy) return;
    const attempt = ++generation.current;
    setBusy(true); setError(null);
    try {
      let id = session.current;
      if (!id) {
        const created = await browserApi.createReader(conversationId, taskId);
        if (!alive.current || generation.current !== attempt) { await browserApi.closeReader(created.session_id); return; }
        id = created.session_id; session.current = id;
      }
      const next = await browserApi.readerAction(id, action);
      if (!alive.current || generation.current !== attempt) return;
      setFrame(next); setUrl(next.url); onTitle(next.title);
    } catch (cause) {
      if (!alive.current || generation.current !== attempt) return;
      const code = (cause as { detail?: { code?: string } }).detail?.code;
      // The remote page may have navigated before capture failed. Do not keep
      // presenting its previous screenshot/link controls as a current view.
      setFrame(null);
      setError(code === "browser.setup_required" ? "dock.setupRequired" : code === "browser.stale_view" ? "dock.stale" : "dock.error");
      if (code === "browser.session_closed" || code === "browser.session_expired" || code === "browser.runtime_failed") session.current = null;
    } finally { if (alive.current && generation.current === attempt) setBusy(false); }
  }
  return <div className="flex h-full min-h-0 flex-col">
    <p className="border-b border-border p-3 text-xs leading-relaxed text-muted-foreground">{t("dock.readerLimits")}</p>
    <form className="flex gap-2 p-3" onSubmit={event => { event.preventDefault(); void act({ action: "navigate", url: url.trim() }); }}>
      <input type="url" required pattern="https://.*" maxLength={4000} aria-label={t("browser.url")}
        className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm" placeholder="https://example.com"
        value={url} onChange={event => setUrl(event.target.value)} disabled={busy} />
      <button className={button} disabled={busy || !url.trim()} aria-label={t("browser.open")}><ArrowRight size={16} /></button>
    </form>
    <div className="flex items-center gap-2 px-3 pb-3">
      <button className={button} disabled={busy || !frame?.can_back} onClick={() => void act({ action: "back" })} aria-label={t("dock.back")}><ArrowLeft size={15} /></button>
      <button className={button} disabled={busy || !frame?.can_forward} onClick={() => void act({ action: "forward" })} aria-label={t("dock.forward")}><ArrowRight size={15} /></button>
      <button className={button} disabled={busy || !frame} onClick={() => void act({ action: "refresh" })} aria-label={t("dock.refresh")}><RefreshCw size={15} /></button>
      <button className={button} disabled={busy || !frame} onClick={() => void act({ action: "scroll", direction: -1 })} aria-label={t("dock.scrollUp")}><ArrowUp size={15} /></button>
      <button className={button} disabled={busy || !frame} onClick={() => void act({ action: "scroll", direction: 1 })} aria-label={t("dock.scrollDown")}><ArrowDown size={15} /></button>
      <button className={button} disabled={!busy && !frame && !session.current} onClick={() => void stop()} aria-label={t("dock.stop")}><Square size={15} /></button>
    </div>
    {error && <p role="alert" className="px-3 pb-3 text-sm text-destructive">{t(error)}</p>}
    {busy && <p role="status" className="px-3 pb-3 text-sm">{t("browser.loading")}</p>}
    <div className="min-h-0 flex-1 overflow-y-auto">
      {!frame && !busy && <p className="p-6 text-sm text-muted-foreground">{t("dock.openPage")}</p>}
      {frame && <>
        <img src={`data:image/jpeg;base64,${frame.screenshot}`} alt={t("browser.screenshot")} className="w-full bg-white" />
        <details className="border-b border-border p-3"><summary className="cursor-pointer text-sm">{t("dock.links", { count: frame.links.length })}</summary>
          <ul className="mt-2 space-y-2">{frame.links.map(link => <li key={link.id}><button className="w-full break-words rounded border border-border p-2 text-left text-xs hover:bg-surface disabled:opacity-40"
            disabled={busy} onClick={() => void act({ action: "link", link_id: link.id, revision: frame.revision })}>
            <span className="block">{link.label || link.url}</span><span className="block break-all text-muted-foreground">{link.url}</span>
          </button></li>)}</ul>
        </details>
        <details className="p-3"><summary className="cursor-pointer text-sm">{t("dock.pageText")}</summary><pre className="mt-3 whitespace-pre-wrap break-words text-xs leading-relaxed">{frame.text}</pre></details>
      </>}
    </div>
  </div>;
}

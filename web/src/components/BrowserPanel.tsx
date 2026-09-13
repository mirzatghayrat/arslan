import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { browserApi, type BrowserState, type BrowserVisit } from "../api/browser";
import { api } from "../api/client";
import ArtifactDownloads from "./ArtifactDownloads";

const control = "rounded-lg border border-border bg-background px-3 py-2 text-sm disabled:opacity-40";

export default function BrowserPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const dialog = useRef<HTMLDialogElement>(null);
  const [state, setState] = useState<BrowserState | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const [visit, setVisit] = useState<BrowserVisit | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const pending = useRef<{ url: string; key: string } | null>(null);
  const running = runId !== null && (!visit || visit.status === "recording");

  useEffect(() => {
    if (open) { dialog.current?.showModal(); browserApi.status().then(setState).catch(() => setError(true)); }
    else if (dialog.current?.open) dialog.current.close();
  }, [open]);
  useEffect(() => {
    if (!open || runId === null || (visit && visit.status !== "recording")) return;
    let gone = false;
    const poll = () => browserApi.visit(runId).then(value => { if (!gone) setVisit(value); })
      .catch(() => { if (!gone) setError(true); });
    void poll();
    const timer = setInterval(poll, 1000);
    return () => { gone = true; clearInterval(timer); };
  }, [open, runId, visit?.status]);
  const screenshot = visit?.artifacts.find(file => file.title === "page.png");
  useEffect(() => {
    setImage(null);
    if (!screenshot) return;
    let gone = false; let localUrl: string | null = null;
    api.downloadRunArtifact(screenshot.run_id, screenshot.filename).then(blob => {
      if (gone) return;
      localUrl = URL.createObjectURL(blob); setImage(localUrl);
    }).catch(() => { if (!gone) setError(true); });
    return () => { gone = true; if (localUrl) URL.revokeObjectURL(localUrl); };
  }, [screenshot?.filename]);

  async function start() {
    setBusy(true); setError(false);
    const target = url.trim();
    if (pending.current?.url !== target) pending.current = { url: target, key: crypto.randomUUID() };
    try {
      const reply = await browserApi.start(target, pending.current.key);
      setVisit(null); setRunId(reply.run_id); pending.current = null;
    } catch { setError(true); } finally { setBusy(false); }
  }
  async function setup() {
    setBusy(true); setError(false);
    try { setState(await browserApi.setup()); } catch { setError(true); }
    finally { setBusy(false); }
  }

  return <dialog ref={dialog} onCancel={onClose} aria-label={t("browser.title")}
    className="m-auto w-[min(1100px,94vw)] max-h-[90vh] rounded-2xl border border-border bg-background text-foreground p-0 backdrop:bg-black/60">
    <div className="p-5 space-y-4 select-text">
      <header className="flex items-start justify-between gap-4"><div>
        <h2 className="text-lg font-semibold">{t("browser.title")}</h2>
        <p className="text-sm text-muted-foreground mt-1">{t("browser.description")}</p>
      </div><button className={control} onClick={onClose}>{t("browser.close")}</button></header>
      <p className="text-xs text-muted-foreground border border-border rounded-lg p-3">{t("browser.limitations")}</p>
      {error && <p role="alert" className="text-danger text-sm">{t("browser.error")}</p>}
      {!state && <p role="status">{t("browser.loading")}</p>}
      {state && !state.ready && <div className="rounded-xl border border-border p-4 space-y-3">
        <p>{t(`browser.${state.reason}`)}</p>
        {state.reason === "setup_required" && <><p className="text-sm text-muted-foreground">{t("browser.setup_notice")}</p>
          <button className={control} disabled={busy} onClick={setup}>{t(busy ? "browser.loading" : "browser.setup")}</button></>}
      </div>}
      <form className="flex gap-2" onSubmit={e => { e.preventDefault(); void start(); }}>
        <input className={control + " min-w-0 flex-1"} type="url" required pattern="https://.*" maxLength={4000}
          value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com" aria-label={t("browser.url")}
          disabled={busy || running || !state?.ready} />
        <button className={control} disabled={busy || running || !state?.ready || !url.trim()}>{t("browser.open")}</button>
        {running && <button type="button" className={control} onClick={() => api.cancelRun(runId!).catch(() => setError(true))}>{t("browser.stop")}</button>}
      </form>
      {runId !== null && <p role="status" className="text-sm text-muted-foreground">#{runId} · {t(visit?.status === "cancelled" ? "browser.cancelled" : `recipes.status_${visit?.status === "recording" || !visit ? "running" : visit.status}`)}</p>}
      {visit?.status === "failed" && <p className="text-sm text-danger">{t("browser.error")}</p>}
      {visit?.result && <><p className="text-xs text-muted-foreground">{t("browser.blocked", { n: visit.result.blocked_connections })}</p>
        <div className="grid md:grid-cols-2 gap-4">
          <div className="rounded-xl border border-border overflow-hidden bg-white">{image && <img src={image} alt={t("browser.screenshot")} className="w-full" />}</div>
          <pre className="rounded-xl border border-border p-4 text-xs leading-relaxed whitespace-pre-wrap break-words max-h-[420px] overflow-auto">{visit.result.text}</pre>
        </div><ArtifactDownloads files={visit.artifacts} /></>}
    </div>
  </dialog>;
}

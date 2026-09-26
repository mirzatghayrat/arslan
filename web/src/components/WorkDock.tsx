import { useEffect, useRef, useState } from "react";
import { File, Globe, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { OPEN_ARTIFACT, restoreDock, saveDock, validArtifact, type DockTab } from "../lib/workDock";
import BrowserReader from "./BrowserReader";
import BrowserPanel from "./BrowserPanel";
import ArtifactPreview from "./ArtifactPreview";

export default function WorkDock({ open, onOpen, onClose, conversationId, taskId, temporary }: {
  open: boolean; onOpen: () => void; onClose: () => void; conversationId: string; taskId: string | null; temporary: boolean;
}) {
  const { t } = useTranslation();
  const initial = useRef(restoreDock());
  const [tabs, setTabs] = useState<DockTab[]>(initial.current.tabs);
  const [selected, setSelected] = useState(initial.current.tabs[0]?.id ?? "");
  const [width, setWidth] = useState(initial.current.width);
  const [narrow, setNarrow] = useState(() => window.innerWidth < 768);
  const [legacy, setLegacy] = useState(false);
  const [limit, setLimit] = useState(false);
  const previousConversation = useRef(conversationId);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const update = () => setNarrow(window.innerWidth < 768);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  useEffect(() => {
    if (!open || !narrow) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>("header button")?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, [open, narrow]);
  useEffect(() => {
    if (previousConversation.current !== conversationId) setTabs(old => old.filter(tab => !tab.temporary));
    previousConversation.current = conversationId;
  }, [conversationId]);
  useEffect(() => { saveDock(tabs, width, temporary); }, [tabs, width, temporary]);
  useEffect(() => {
    if (!temporary) return;
    // Privacy can change without changing the conversation ID. Closing the old
    // readers releases their sessions; remove their prior restore records too.
    // Newly opened temporary tabs remain session-only and are filtered by saveDock.
    const next = tabs.filter(tab => !(tab.kind === 'browser'
      && tab.conversationId === conversationId && !tab.temporary));
    if (next.length === tabs.length) return;
    setTabs(next);
    saveDock(next, width, false);
  }, [conversationId, temporary, tabs, width]);
  useEffect(() => {
    if (!tabs.some(tab => tab.id === selected)) setSelected(tabs[0]?.id ?? "");
  }, [tabs, selected]);
  useEffect(() => {
    function openFile(event: Event) {
      const file = (event as CustomEvent).detail;
      if (!validArtifact(file)) return;
      const existing = tabs.find(tab => tab.kind === "artifact" && tab.file.run_id === file.run_id && tab.file.filename === file.filename && tab.file.sha256 === file.sha256);
      if (existing) setSelected(existing.id);
      else if (tabs.length < 8) {
        const id = crypto.randomUUID(); setTabs(old => [...old, { id, kind: "artifact", file, temporary }]); setSelected(id);
      } else setLimit(true);
      onOpen();
    }
    window.addEventListener(OPEN_ARTIFACT, openFile);
    return () => window.removeEventListener(OPEN_ARTIFACT, openFile);
  }, [tabs, temporary, onOpen]);
  function addBrowser() {
    if (tabs.length >= 8) { setLimit(true); return; }
    const id = crypto.randomUUID();
    setTabs(old => [...old, { id, kind: "browser", conversationId, taskId, temporary }]); setSelected(id); setLimit(false);
  }
  function resize(value: number) { setWidth(Math.max(300, Math.min(760, window.innerWidth - 360, value))); }
  function moveTab(event: React.KeyboardEvent, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    setSelected(tabs[next].id);
    panel.current?.querySelector<HTMLButtonElement>(`[data-tab-id="${tabs[next].id}"]`)?.focus();
  }
  if (!open) return null;
  return <aside ref={panel} aria-label={t("dock.title")} role={narrow ? "dialog" : undefined} aria-modal={narrow || undefined}
    style={{ width: narrow ? "100%" : width, maxWidth: narrow ? "none" : "55vw" }}
    className={`${narrow ? "fixed inset-0 z-[100]" : "relative z-20"} flex h-full min-w-0 shrink-0 flex-col border-l border-border bg-background`}
    onKeyDown={event => {
      if (!narrow || legacy) return;
      if (event.key === "Escape") { event.stopPropagation(); onClose(); }
      if (event.key === "Tab") {
        const elements = Array.from(panel.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]),input:not([disabled]),a[href],summary,[tabindex="0"]') ?? [])
          .filter(element => element.getClientRects().length > 0 && element.tabIndex !== -1);
        const first = elements[0], last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
    {!narrow && <div role="separator" tabIndex={0} aria-label={t("dock.resize")} aria-orientation="vertical" aria-valuemin={300} aria-valuemax={760} aria-valuenow={Math.round(width)}
      className="absolute -left-1 top-0 z-30 h-full w-2 cursor-col-resize touch-none hover:bg-primary/25 focus:bg-primary/25"
      onKeyDown={event => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); resize(width + (event.key === "ArrowLeft" ? 20 : -20)); } }}
      onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); }}
      onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) resize(window.innerWidth - event.clientX); }}
      onPointerUp={event => event.currentTarget.releasePointerCapture(event.pointerId)} />}
    <header className="flex items-center gap-2 border-b border-border p-3"><h2 className="min-w-0 flex-1 text-sm font-semibold">{t("dock.title")}</h2>
      <button className="rounded p-1.5 hover:bg-surface" onClick={addBrowser} aria-label={t("dock.newBrowser")}><Plus size={17} /></button>
      <button className="rounded p-1.5 hover:bg-surface" onClick={onClose} aria-label={t("dock.close")}><X size={17} /></button>
    </header>
    <div role="tablist" aria-label={t("dock.tabs")} className="flex shrink-0 overflow-x-auto border-b border-border">
      {tabs.map((tab, index) => <div key={tab.id} className={`flex max-w-[210px] shrink-0 items-center border-r border-border ${tab.id === selected ? "bg-surface" : ""}`}>
        <button role="tab" id={`dock-tab-${tab.id}`} aria-controls={`dock-content-${tab.id}`} aria-selected={tab.id === selected} tabIndex={tab.id === selected ? 0 : -1}
          data-tab-id={tab.id} onKeyDown={event => moveTab(event, index)} onClick={() => setSelected(tab.id)} className="flex min-w-0 items-center gap-2 px-3 py-2 text-xs">
          {tab.kind === "browser" ? <Globe size={14} className="shrink-0" /> : <File size={14} className="shrink-0" />}
          <span className="truncate">{tab.kind === "browser" ? tab.title || t("dock.browser") : tab.file.title}</span>
        </button>
        <button className="shrink-0 p-1.5 hover:bg-background" aria-label={t("dock.closeTab")}
          onClick={() => { setTabs(old => old.filter(item => item.id !== tab.id)); setLimit(false); }}><X size={13} /></button>
      </div>)}
    </div>
    {limit && <p role="alert" className="p-3 text-xs text-destructive">{t("dock.tabLimit")}</p>}
    {!tabs.length && <div className="space-y-4 p-5 text-sm text-muted-foreground"><p>{t("dock.empty")}</p><button className="rounded-lg border border-border px-3 py-2 text-foreground" onClick={addBrowser}>{t("dock.newBrowser")}</button></div>}
    {tabs.map(tab => <div key={tab.id} role="tabpanel" id={`dock-content-${tab.id}`} aria-labelledby={`dock-tab-${tab.id}`}
      hidden={tab.id !== selected} className="min-h-0 flex-1 overflow-hidden">
      {tab.kind === "browser" ? <div className="flex h-full min-h-0 flex-col">
        <p className="shrink-0 border-b border-border px-3 py-1 text-[10px] text-muted-foreground">{t(tab.conversationId === conversationId ? "dock.currentConversation" : "dock.otherConversation")}</p>
        <div className="min-h-0 flex-1"><BrowserReader conversationId={tab.conversationId} taskId={tab.taskId}
          onTitle={title => setTabs(old => old.map(item => item.id === tab.id && item.kind === "browser" ? { ...item, title } : item))} /></div>
      </div> : <ArtifactPreview file={tab.file} visible={tab.id === selected} />}
    </div>)}
    <footer className="shrink-0 border-t border-border p-2"><button className="text-xs text-muted-foreground underline" onClick={() => setLegacy(true)}>{t("dock.staticPreview")}</button></footer>
    <BrowserPanel open={legacy} onClose={() => setLegacy(false)} />
  </aside>;
}

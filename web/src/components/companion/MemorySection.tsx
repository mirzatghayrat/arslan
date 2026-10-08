import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import BrainSection from "../brain/BrainSection";
import { Button } from "../kit";
import Materials from "./Materials";
import MemoryList from "./MemoryList";

export const MEMORY_VIEW_KEY = "arslan.memory.view";
/** 0.1.55 §13: one page with two views. Materials is a sub-page reached from the rail. */
export type MemoryView = "list" | "graph";
export function initialMemoryView(legacy: boolean): MemoryView {
  try {
    const value = localStorage.getItem(MEMORY_VIEW_KEY);
    if (value === "list" || value === "graph") return value;
    // Before 0.1.55 the views were about / materials / graph.
    if (value === "about" || value === "materials") return "list";
  } catch { /* Storage is optional. */ }
  return legacy ? "graph" : "list";
}

type MaterialsMode = "browse" | "feed" | "note";

export default function MemorySection({ legacy = false }: { legacy?: boolean }) {
  const { t } = useTranslation();
  const [view, setView] = useState<MemoryView>(() => initialMemoryView(legacy));
  const [materials, setMaterials] = useState<MaterialsMode | null>(null);
  const [addRequest, setAddRequest] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    try { localStorage.setItem(MEMORY_VIEW_KEY, view); } catch { /* Storage is optional. */ }
  }, [view]);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent) => { if (!menu.current?.contains(event.target as Node)) setMenuOpen(false); };
    const esc = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [menuOpen]);
  const add = (what: "memory" | "feed" | "note") => {
    setMenuOpen(false);
    if (what === "memory") { setMaterials(null); setView("list"); setAddRequest(n => n + 1); }
    else setMaterials(what);
  };
  const item = "block w-full rounded-md px-3 py-1.5 text-left text-[13px] hover:bg-fill";

  return <div className="flex h-full min-h-0 flex-col">
    <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-5 py-3 sm:px-8">
      {materials ? <button data-testid="memory-back" className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"
        onClick={() => setMaterials(null)}><ArrowLeft size={14} />{t("memoryPage.back")}</button>
        : <div className="min-w-0 flex-1">
          <h1 className="text-[20px] font-bold leading-tight">{t("memoryPage.title")}</h1>
          <p className="mt-0.5 max-w-2xl text-[12.5px] text-muted-foreground">{t("memoryPage.intro")}</p>
        </div>}
      {materials && <span className="flex-1" />}
      <div ref={menu} className="relative">
        <Button size="sm" aria-haspopup="menu" aria-expanded={menuOpen} data-testid="memory-add" onClick={() => setMenuOpen(v => !v)}>
          <Plus size={13} />{t("memoryPage.add")}</Button>
        {menuOpen && <div role="menu" className="absolute right-0 top-full z-30 mt-1 w-44 rounded-lg border border-border bg-background p-1 shadow-kit">
          <button role="menuitem" className={item} onClick={() => add("memory")}>{t("memoryPage.addMemory")}</button>
          <button role="menuitem" className={item} onClick={() => add("feed")}>{t("memoryPage.addMaterial")}</button>
          <button role="menuitem" className={item} onClick={() => add("note")}>{t("memoryPage.addNote")}</button>
        </div>}
      </div>
      {!materials && <div role="tablist" aria-label={t("memoryPage.title")} className="inline-flex rounded-lg bg-fill p-0.5">
        {(["list", "graph"] as const).map(key => <button key={key} role="tab" aria-selected={view === key} data-testid={`memory-view-${key}`}
          className={`rounded-md px-3 py-1 text-[12.5px] ${view === key ? "bg-background font-semibold text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          onClick={() => setView(key)}>{t(key === "list" ? "memoryPage.viewList" : "memoryPage.viewGraph")}</button>)}
      </div>}
    </header>
    <div className="relative flex min-h-0 flex-1">
      {materials ? <Materials mode={materials} />
        : view === "list" ? <MemoryList addRequest={addRequest} onAddHandled={() => setAddRequest(0)} onOpenMaterials={setMaterials} />
        : <BrainSection page />}
    </div>
  </div>;
}

import { useEffect, useState } from "react";
import { Brain, FileText, Network } from "lucide-react";
import { useTranslation } from "react-i18next";
import BrainSection from "../brain/BrainSection";
import Materials from "./Materials";
import MemoryList from "./MemoryList";

export const MEMORY_VIEW_KEY = "arslan.memory.view";
export type MemoryView = "about" | "materials" | "graph";
export function initialMemoryView(legacy: boolean): MemoryView {
  try {
    const value = localStorage.getItem(MEMORY_VIEW_KEY);
    if (value === "about" || value === "materials" || value === "graph") return value;
  } catch { /* Storage is optional. */ }
  return legacy ? "graph" : "about";
}
export default function MemorySection({ legacy = false }: { legacy?: boolean }) {
  const { t } = useTranslation();
  const [view, setView] = useState<MemoryView>(() => initialMemoryView(legacy));
  useEffect(() => {
    try { localStorage.setItem(MEMORY_VIEW_KEY, view); } catch { /* Storage is optional. */ }
  }, [view]);
  return <div className="flex h-full min-h-0 flex-col">
    <nav className="flex shrink-0 gap-1 border-b border-border px-5 py-2" aria-label={t("companion.memory")}>
      {([["about", Brain], ["materials", FileText], ["graph", Network]] as const).map(([key, Icon]) => <button key={key}
        className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${view === key ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-foreground/5"}`}
        aria-current={view === key ? "page" : undefined} onClick={() => setView(key)}><Icon size={16} />{t(`companion.${key}`)}</button>)}
    </nav>
    <div className="relative min-h-0 flex-1">{view === "about" ? <MemoryList /> : view === "materials" ? <Materials /> : <BrainSection />}</div>
  </div>;
}

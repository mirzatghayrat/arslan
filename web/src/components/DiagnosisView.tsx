import { useEffect, useRef, useState } from "react";
import DiagnosisCatalog from "./DiagnosisCatalog";
import SpawnRunDetail from "./SpawnRunDetail";
import RunReplay from "./RunReplay";

type Selection =
  | null
  | { spawnId: number; name: string | null; runId?: undefined }
  | { spawnId: number; name: string | null; runId: number };

const NARROW_BREAKPOINT = 700;

/**
 * Standalone full-width diagnosis section (catalog → spawn → run) mounted as a
 * top-level nav section, separate from the conversation-rail EvalDock dock.
 */
export default function DiagnosisView() {
  const [sel, setSel] = useState<Selection>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [narrow, setNarrow] = useState(false);

  // Measure the container's own width (not the window) so the catalog switches
  // to cards whenever its host is narrow — whether that's a small viewport or a
  // squeezed panel. ResizeObserver is undefined in jsdom; guard so tests don't
  // crash, and just default to `narrow=false` there.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setNarrow(entry.contentRect.width < NARROW_BREAKPOINT);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="flex-1 h-full overflow-auto p-6">
      {sel == null && (
        <DiagnosisCatalog
          onClose={() => {}}
          onSelectSpawn={(spawnId, name) => setSel({ spawnId: spawnId ?? 0, name })}
          narrow={narrow}
        />
      )}

      {sel != null && sel.runId === undefined && (
        <>
          <div data-testid="diag-breadcrumb" className="text-[11px] font-mono text-muted-foreground mb-3 flex items-center gap-1.5">
            <span className="cursor-pointer hover:text-foreground" onClick={() => setSel(null)}>诊断台</span>
            <span>/</span>
            <span className="text-foreground">{sel.name}</span>
          </div>
          <SpawnRunDetail
            spawnId={sel.spawnId}
            spawnName={sel.name}
            onBack={() => setSel(null)}
            onSelectRun={(runId) => setSel({ runId, spawnId: sel.spawnId, name: sel.name })}
          />
        </>
      )}

      {sel != null && sel.runId !== undefined && (
        <>
          <div data-testid="diag-breadcrumb" className="text-[11px] font-mono text-muted-foreground mb-3 flex items-center gap-1.5">
            <span className="cursor-pointer hover:text-foreground" onClick={() => setSel(null)}>诊断台</span>
            <span>/</span>
            <span className="cursor-pointer hover:text-foreground" onClick={() => setSel({ spawnId: sel.spawnId, name: sel.name })}>{sel.name}</span>
            <span>/</span>
            <span className="text-foreground">run #{sel.runId}</span>
          </div>
          <RunReplay
            runId={sel.runId}
            onClose={() => setSel({ spawnId: sel.spawnId, name: sel.name })}
          />
        </>
      )}
    </div>
  );
}

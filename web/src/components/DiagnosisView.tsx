import { useState } from "react";
import DiagnosisCatalog from "./DiagnosisCatalog";
import SpawnRunDetail from "./SpawnRunDetail";
import RunReplay from "./RunReplay";

type Selection =
  | null
  | { spawnId: number; name: string | null; runId?: undefined }
  | { spawnId: number; name: string | null; runId: number };

/**
 * Standalone full-width diagnosis section (catalog → spawn → run) mounted as a
 * top-level nav section, separate from the conversation-rail EvalDock dock.
 */
export default function DiagnosisView() {
  const [sel, setSel] = useState<Selection>(null);

  return (
    <div className="flex-1 h-full overflow-auto p-6">
      {sel == null && (
        <DiagnosisCatalog
          onClose={() => {}}
          onSelectSpawn={(spawnId, name) => setSel({ spawnId: spawnId ?? 0, name })}
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

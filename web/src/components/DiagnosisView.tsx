import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import DiagnosisCatalog from "./DiagnosisCatalog";
import SpawnRunDetail from "./SpawnRunDetail";
import RunReplay from "./RunReplay";
import EvolutionInbox from "./EvolutionInbox";
import UsageCard from "./UsageCard";

type Selection =
  | null
  | { spawnId: number; name: string | null; runId?: undefined }
  | { spawnId: number; name: string | null; runId: number };

type Tab = "diag" | "evolution";

const NARROW_BREAKPOINT = 700;

/**
 * Standalone full-width diagnosis section (catalog → spawn → run) mounted as a
 * top-level nav section, separate from the conversation-rail EvalDock dock. The
 * "进化" tab hosts the S2 evolution inbox + promotion cards (spec §E7); a pair's
 * "查看重放" opens the same RunReplay this view already uses.
 */
export default function DiagnosisView() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("diag");
  const [sel, setSel] = useState<Selection>(null);
  // A replay opened from the evolution inbox (a proposal pair's run id). Kept
  // separate from the catalog drill `sel` so it overlays either tab cleanly.
  const [evoRun, setEvoRun] = useState<number | null>(null);
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

  const tabBtn = (id: Tab, label: string) => (
    <button
      type="button"
      className={
        tab === id
          ? "px-3 py-1.5 text-[12px] font-mono uppercase tracking-wider rounded-lg bg-primary text-primary-foreground"
          : "px-3 py-1.5 text-[12px] font-mono uppercase tracking-wider rounded-lg text-muted-foreground hover:text-foreground"
      }
      onClick={() => {
        setTab(id);
        setEvoRun(null);
      }}
      data-testid={`diag-tab-${id}`}
    >
      {label}
    </button>
  );

  return (
    <div ref={containerRef} className="flex-1 h-full overflow-auto p-6">
      <div className="flex items-center gap-1.5 mb-4">
        {tabBtn("diag", t("evolution.inbox.diag_tab"))}
        {tabBtn("evolution", t("evolution.inbox.tab"))}
      </div>

      {/* A replay opened from the evolution inbox overlays everything. */}
      {evoRun != null ? (
        <>
          <div className="text-[11px] font-mono text-muted-foreground mb-3 flex items-center gap-1.5">
            <span className="cursor-pointer hover:text-foreground" onClick={() => setEvoRun(null)}>
              {t("evolution.inbox.tab")}
            </span>
            <span>/</span>
            <span className="text-foreground">run #{evoRun}</span>
          </div>
          <RunReplay runId={evoRun} onClose={() => setEvoRun(null)} />
        </>
      ) : tab === "evolution" ? (
        <EvolutionInbox onOpenRun={(runId) => setEvoRun(runId)} />
      ) : (
        <>
          {sel == null && (
            <>
              <DiagnosisCatalog
                onClose={() => {}}
                onSelectSpawn={(spawnId, name) => setSel({ spawnId: spawnId ?? 0, name })}
                narrow={narrow}
              />
              {/* S3-M3 cost visibility: fleet-wide usage summary (tokens + honest USD). */}
              <UsageCard />
            </>
          )}

          {sel != null && sel.runId === undefined && (
            <>
              <div data-testid="diag-breadcrumb" className="text-[11px] font-mono text-muted-foreground mb-3 flex items-center gap-1.5">
                <span className="cursor-pointer hover:text-foreground" onClick={() => setSel(null)}>Diagnostics</span>
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
                <span className="cursor-pointer hover:text-foreground" onClick={() => setSel(null)}>Diagnostics</span>
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
        </>
      )}
    </div>
  );
}

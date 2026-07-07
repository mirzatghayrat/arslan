import type { BrainBranch, BrainLeaf } from "../../api/client";
import { hueVar } from "./hues";

/** The three dark-orange type panels below the orrery — material / learning /
 * profile, each row surfacing provenance · usage · confidence. Click → detail. */
export default function BrainPanels({ branches, onPick }: { branches: BrainBranch[]; onPick: (l: BrainLeaf) => void }) {
  return (
    <div className="grid grid-cols-3 gap-3 px-4 pb-4">
      {branches.map((b) => (
        <div key={b.kind} className="rounded-xl bg-surface border border-border overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border"
            style={{ borderTop: `2px solid ${hueVar(b.kind)}` }}>
            <span className="text-[12px] font-medium text-foreground">{b.label}</span>
            <span className="ml-auto font-mono text-[11px] text-subtle-foreground tabular-nums">{b.children.length}</span>
          </div>
          <div className="flex flex-col max-h-[260px] overflow-auto">
            {b.children.length === 0 ? (
              <div className="px-3 py-4 text-[11px] text-subtle-foreground">暂无</div>
            ) : (
              b.children.slice(0, 60).map((l) => (
                <button key={l.ref} onClick={() => onPick(l)}
                  className="text-left px-3 py-2 hover:bg-foreground/[0.04] border-b border-border/40">
                  <div className="text-[12px] text-foreground truncate">{l.label}</div>
                  <div className="text-[10.5px] text-subtle-foreground font-mono">
                    {l.provenance ?? ""}
                    {l.usage_count ? ` · 用过 ${l.usage_count}` : ""}
                    {l.confidence != null ? ` · 置信 ${l.confidence.toFixed(2)}` : ""}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

import { useMemo, useState } from "react";
import type { BrainLeaf } from "../../api/client";
import { useKnowledgeTree } from "../../hooks/useKnowledgeTree";
import { useBrainTree, brainBranchesToTree, recentIds } from "../../hooks/useBrainTree";
import { feedFile } from "../../lib/feed";
import BrainEntryDetail from "./BrainEntryDetail";
import BrainPanels from "./BrainPanels";
import KnowledgeNav from "./KnowledgeNav";
import KnowledgeSunburst from "./KnowledgeSunburst";

export default function BrainSection() {
  // Left nav keeps the collection-management tree (feed / delete / rename); the
  // right side (orrery + panels) reads the new typed /brain/tree with usage.
  const { tree, refresh: refreshNav } = useKnowledgeTree();
  const { branches, loading, error, refresh: refreshBrain } = useBrainTree();
  const refresh = () => { refreshNav(); refreshBrain(); };

  const brainTree = useMemo(() => brainBranchesToTree(branches), [branches]);
  const glowIds = useMemo(() => recentIds(branches), [branches]);

  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [picked, setPicked] = useState<BrainLeaf | null>(null);
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (!files.length) return;
    let ok = 0; const failed: string[] = [];
    for (const file of files) {          // sequential: reuse just-created buckets, avoid create races
      setStatus(`投喂中 ${ok + failed.length + 1}/${files.length}…`);
      try { await feedFile(file); ok += 1; } catch { failed.push(file.name); }
    }
    refresh();
    setStatus(failed.length ? `已投喂 ${ok},失败:${failed.join("、")}` : `已投喂 ${ok} 项`);
    setTimeout(() => setStatus(null), 4000);
  };

  return (
    <div data-dropzone="1" className="flex-1 flex h-full overflow-hidden relative"
      onDragOver={(e) => { if (hasFiles(e)) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
      onDrop={(e) => void onDrop(e)}>
      <KnowledgeNav tree={tree} focusedId={focusedId} onFocus={setFocusedId} onChanged={refresh} />
      <div className="flex-1 relative h-full flex flex-col overflow-hidden">
        {/* A′: height-capped orrery on top, dense panels peeking below */}
        <div className="flex-none relative" style={{ maxHeight: "56%" }}>
          {error
            ? <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-muted-foreground">加载知识图谱失败</div>
            : <KnowledgeSunburst tree={brainTree} focusedId={focusedId} onFocus={setFocusedId} glowIds={glowIds} className="w-full h-full" />}
          {loading && <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-subtle-foreground uppercase tracking-widest pointer-events-none">loading…</div>}
        </div>
        <div className="flex-1 overflow-auto pt-2">
          <BrainPanels branches={branches} onPick={setPicked} />
        </div>
        {picked && <BrainEntryDetail leaf={picked} onClose={() => setPicked(null)} />}
      </div>
      {status && <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 text-[12px] px-3 py-1.5 rounded-lg bg-surface border border-border text-foreground">{status}</div>}
      {dragging && (
        <div data-drop-overlay="1" className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none bg-primary/[0.10] border-2 border-dashed border-primary rounded-2xl">
          <div className="text-[15px] font-medium text-primary">松开投喂到第二大脑</div>
        </div>
      )}
    </div>
  );
}

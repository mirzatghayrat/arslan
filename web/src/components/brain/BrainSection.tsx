import { useState } from "react";
import { useKnowledgeTree } from "../../hooks/useKnowledgeTree";
import KnowledgeNav from "./KnowledgeNav";
import KnowledgeSunburst from "./KnowledgeSunburst";

export default function BrainSection() {
  const { tree, loading, error, refresh } = useKnowledgeTree();
  const [focusedId, setFocusedId] = useState<string | null>(null);
  return (
    <div className="flex-1 flex h-full overflow-hidden">
      <KnowledgeNav tree={tree} focusedId={focusedId} onFocus={setFocusedId} onChanged={refresh} />
      <div className="flex-1 relative h-full">
        {error
          ? <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-muted-foreground">加载知识图谱失败</div>
          : <KnowledgeSunburst tree={tree} focusedId={focusedId} onFocus={setFocusedId} className="w-full h-full" />}
        {loading && <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-subtle-foreground uppercase tracking-widest pointer-events-none">loading…</div>}
      </div>
    </div>
  );
}

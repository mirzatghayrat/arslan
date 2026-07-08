import { useMemo, useState } from "react";
import { api, type BrainLeaf } from "../../api/client";
import { useBrainTree, recentIds } from "../../hooks/useBrainTree";
import { feedFile } from "../../lib/feed";
import BrainEntryDetail from "./BrainEntryDetail";
import BrainGraph from "./BrainGraph";
import BrainNav from "./BrainNav";
import NoteEditor from "./NoteEditor";

export default function BrainSection() {
  const { branches, loading, error, refresh } = useBrainTree();
  const glowIds = useMemo(() => recentIds(branches), [branches]);
  const allLabels = useMemo(() => branches.flatMap((b) => b.children.map((l) => l.label)), [branches]);

  const [tab, setTab] = useState<"graph" | "content">("graph");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [picked, setPicked] = useState<BrainLeaf | null>(null);
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  // picking anything (from tree or graph) opens it in the content tab
  const pick = (l: BrainLeaf) => { if ((l.kind as string) === "ghost") return; setPicked(l); setTab("content"); };

  const createNote = async () => {
    const n = await api.createNote({ title: "未命名笔记" });
    refresh();
    pick({ kind: "note", ref: `note:${n.id}`, label: n.title, provenance: "手写",
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 });
  };
  const createNoteWithTitle = async (title: string) => {
    const n = await api.createNote({ title });
    refresh();
    pick({ kind: "note", ref: `note:${n.id}`, label: n.title, provenance: "手写",
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 });
  };
  const generateFromTopic = async (topic: string) => { await api.generateNotes(topic); refresh(); };
  const tagFilter = (_tag: string) => setTab("content");   // v1: chip focuses the content side; search still filters the tree

  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const files = Array.from(e.dataTransfer?.files ?? []); if (!files.length) return;
    let ok = 0; const failed: string[] = [];
    for (const file of files) {
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
      <BrainNav branches={branches} focusedId={focusedId} onFocus={setFocusedId} onPick={pick} onChanged={refresh}
        tab={tab} onTab={setTab} onTagFilter={tagFilter}
        onCreateNote={() => void createNote()} onGenerate={(t) => void generateFromTopic(t)} />

      <div className="flex-1 relative h-full overflow-hidden">
        {tab === "graph" ? (
          <>
            {error
              ? <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-muted-foreground">加载知识图谱失败</div>
              : <BrainGraph focusedId={focusedId} onFocus={setFocusedId} onPick={pick}
                  onCreateNoteWithTitle={(t) => void createNoteWithTitle(t)} glowIds={glowIds} className="w-full h-full" />}
            {loading && <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-subtle-foreground uppercase tracking-widest pointer-events-none">loading…</div>}
          </>
        ) : picked && picked.kind === "note" ? (
          <NoteEditor noteId={Number(picked.ref.split(":")[1])} onClose={() => setPicked(null)}
            onChanged={refresh} allLabels={allLabels} />
        ) : picked ? (
          <BrainEntryDetail leaf={picked} onClose={() => setPicked(null)} />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-[12px] text-muted-foreground">
            从左侧选一个条目,或切到图谱漫游
          </div>
        )}
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

import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { feedTextOrUrl, feedFileInto } from "../../lib/feed";
import type { TreeNode } from "../../hooks/useKnowledgeTree";
import { hueVar } from "./hues";

interface Props { tree: TreeNode; focusedId: string | null; onFocus: (id: string | null) => void; onChanged: () => void; }

function matches(n: TreeNode, q: string): boolean {
  if (!q) return true;
  if (n.name.toLowerCase().includes(q)) return true;
  return (n.children ?? []).some((c) => matches(c, q));
}

export default function KnowledgeNav({ tree, focusedId, onFocus, onChanged }: Props) {
  const [q, setQ] = useState("");
  const [feed, setFeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setExpanded((prev) => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const ql = q.trim().toLowerCase();
  const cats = useMemo(() => (tree.children ?? []).filter((c) => matches(c, ql)), [tree, ql]);

  const quickFeed = async () => {
    const t = feed.trim();
    if (!t) return;
    setBusy(true); setErr(null);
    try {
      await feedTextOrUrl(t);
      setFeed(""); onChanged();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const [newName, setNewName] = useState("");
  const [showNew, setShowNew] = useState(false);
  const createNamed = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true); setErr(null);
    try { await api.createCollection(name); setNewName(""); setShowNew(false); onChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const Row = ({ n, depth }: { n: TreeNode; depth: number }) => {
    if (!matches(n, ql)) return null;
    const on = focusedId === n.id;
    const hasChildren = (n.children ?? []).length > 0;
    const open = expanded.has(n.id) || (ql !== "" && (n.children ?? []).some((c) => matches(c, ql)));
    const isGroup = n.kind === "category" || n.kind === "collection";
    const collId = n.kind === "collection" ? Number(n.id.replace(/^coll:/, "")) : null;
    return (
      <>
        <div
          {...(collId != null ? {
            "data-coll-id": collId,
            onDragOver: (e: React.DragEvent) => { if (Array.from(e.dataTransfer?.types ?? []).includes("Files")) { e.preventDefault(); e.stopPropagation(); (e.currentTarget as HTMLElement).style.outline = "2px solid var(--primary)"; } },
            onDragLeave: (e: React.DragEvent) => { (e.currentTarget as HTMLElement).style.outline = ""; },
            onDrop: async (e: React.DragEvent) => {
              e.preventDefault(); e.stopPropagation();
              (e.currentTarget as HTMLElement).style.outline = "";
              const files = Array.from(e.dataTransfer?.files ?? []);
              for (const file of files) { try { await feedFileInto(collId, file); } catch { /* row-drop best-effort */ } }
              onChanged();
            },
          } : {})}
          onMouseEnter={() => onFocus(n.id)} onMouseLeave={() => onFocus(null)}
          onClick={() => { if (hasChildren) toggle(n.id); }}
          className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-[13.5px] cursor-default border ${on ? "bg-foreground/[0.05] border-border" : "border-transparent hover:bg-foreground/[0.03]"}`}
          style={{ marginLeft: depth * 12 }}>
          {hasChildren ? (
            <span className="flex-none w-3 text-center text-subtle-foreground text-[11px]">{open ? "▾" : "▸"}</span>
          ) : (
            <span className="flex-none w-3" />
          )}
          {isGroup && <span style={{ background: hueVar(n.hueKey ?? n.name), width: 9, height: 9, borderRadius: 2, flex: "none" }} />}
          <span className="flex-1 truncate text-foreground">{n.name}</span>
          <span className="font-mono text-[11px] text-subtle-foreground tabular-nums">{n.value}</span>
        </div>
        {open && (n.children ?? []).map((c) => <Row key={c.id} n={c} depth={depth + 1} />)}
      </>
    );
  };

  return (
    <aside className="w-[340px] flex-none border-r border-border bg-sidebar flex flex-col h-full select-none">
      <div className="p-3">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your knowledge…"
          className="w-full px-3 py-2 rounded-lg bg-surface border border-border text-[13px] font-mono text-foreground placeholder:text-subtle-foreground" />
      </div>
      <div className="flex-1 overflow-auto px-2 pb-2">
        {cats.map((cat) => (
          <div key={cat.id}>
            <div className="font-mono text-[10.5px] tracking-widest uppercase text-subtle-foreground px-2 pt-3 pb-1">{cat.name}</div>
            {(cat.children ?? []).map((c) => <Row key={c.id} n={c} depth={0} />)}
          </div>
        ))}
      </div>
      <div className="border-t border-border p-3 flex flex-col gap-2">
        {err && <div className="text-[12px] text-danger bg-danger/[0.12] border border-danger/30 rounded-lg px-3 py-2">{err}</div>}
        <input value={feed} onChange={(e) => setFeed(e.target.value)} placeholder="贴文本 / URL 快速投喂…"
          onKeyDown={(e) => { if (e.key === "Enter") void quickFeed(); }}
          className="w-full px-3 py-2 rounded-lg bg-surface border border-border text-[13px] text-foreground placeholder:text-subtle-foreground" />
        <button disabled={busy} onClick={() => void quickFeed()}
          className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-[13.5px] font-medium disabled:opacity-50">
          {busy ? "投喂中…" : "＋ 投喂到共享库"}
        </button>
        {showNew ? (
          <div className="flex gap-2">
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="库名…"
              onKeyDown={(e) => { if (e.key === "Enter") void createNamed(); }}
              className="flex-1 px-3 py-2 rounded-lg bg-surface border border-border text-[13px] text-foreground placeholder:text-subtle-foreground" />
            <button onClick={() => void createNamed()} disabled={busy}
              className="px-3 py-2 rounded-lg border border-border text-[13px] text-foreground disabled:opacity-50">建立</button>
          </div>
        ) : (
          <button onClick={() => setShowNew(true)}
            className="text-[12px] text-subtle-foreground hover:text-foreground text-left">＋ 新建库(命名)</button>
        )}
      </div>
    </aside>
  );
}

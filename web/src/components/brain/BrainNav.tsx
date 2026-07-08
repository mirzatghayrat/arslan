import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import type { BrainBranch, BrainLeaf } from "../../api/client";
import { feedFile, feedTextOrUrl } from "../../lib/feed";
import BrainIndexHealth from "./BrainIndexHealth";
import { hueVar } from "./hues";

interface Props {
  branches: BrainBranch[];
  focusedId: string | null;
  onFocus: (id: string | null) => void;
  onPick: (leaf: BrainLeaf) => void;
  onChanged: () => void;
}

/** The Second Brain's left panel — ONE tree over the SAME three types as the
 * orrery + panels (材料/心得/画像). Hovering a row focuses the matching sunburst
 * wedge (shared focusedId); clicking opens its detail. Feed + index-health live
 * at the bottom, so ingest / structure / health are one integrated surface. */
export default function BrainNav({ branches, focusedId, onFocus, onPick, onChanged }: Props) {
  const [q, setQ] = useState("");
  const [feed, setFeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const ql = q.trim().toLowerCase();

  const toggle = (kind: string) =>
    setCollapsed((prev) => { const n = new Set(prev); n.has(kind) ? n.delete(kind) : n.add(kind); return n; });

  const quickFeed = async () => {
    const t = feed.trim();
    if (!t) return;
    setBusy(true); setErr(null);
    try { await feedTextOrUrl(t); setFeed(""); onChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const pickFiles = async (files: FileList | null) => {
    const list = Array.from(files ?? []);
    if (!list.length) return;
    setBusy(true); setErr(null);
    const failed: string[] = [];
    for (const f of list) { try { await feedFile(f); } catch { failed.push(f.name); } }
    setBusy(false);
    if (failed.length) setErr(`未识别/失败:${failed.join("、")}`);
    onChanged();
  };

  return (
    <aside className="brain-nav">
      <div className="brain-nav__search">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索你的知识…"
          className="brain-nav__search-input" />
      </div>

      <div className="brain-nav__tree">
        {branches.map((b) => {
          const kids = b.children.filter((l) => !ql || l.label.toLowerCase().includes(ql));
          const open = !collapsed.has(b.kind) || ql !== "";
          return (
            <div key={b.kind} className="brain-nav__branch">
              <div className="brain-nav__branch-head" onClick={() => toggle(b.kind)}>
                <span className="brain-nav__caret">{open ? "▾" : "▸"}</span>
                <span className="brain-nav__dot" style={{ background: hueVar(b.kind) }} />
                <span className="brain-nav__branch-label">{b.label}</span>
                <span className="brain-nav__count">{b.children.length}</span>
              </div>
              {open && kids.map((l) => (
                <div
                  key={l.ref}
                  data-testid="brain-nav-row"
                  className={`brain-nav__row${focusedId === l.ref ? " is-focused" : ""}`}
                  onMouseEnter={() => onFocus(l.ref)}
                  onMouseLeave={() => onFocus(null)}
                  onClick={() => onPick(l)}
                >
                  <span className="brain-nav__row-label">{l.label}</span>
                  {l.usage_count ? <span className="brain-nav__row-usage">用过 {l.usage_count}</span> : null}
                </div>
              ))}
              {open && kids.length === 0 && <div className="brain-nav__empty">暂无</div>}
            </div>
          );
        })}
      </div>

      <BrainIndexHealth />

      <div className="brain-nav__feed">
        {err && <div className="brain-nav__err">{err}</div>}
        <input value={feed} onChange={(e) => setFeed(e.target.value)} placeholder="贴文本 / URL 快速投喂…"
          onKeyDown={(e) => { if (e.key === "Enter") void quickFeed(); }}
          className="brain-nav__feed-input" />
        <div className="brain-nav__feed-btns">
          <button disabled={busy || !feed.trim()} onClick={() => void quickFeed()}
            className="brain-nav__feed-primary">{busy ? "投喂中…" : "＋ 投喂到共享库"}</button>
          <button type="button" disabled={busy} title="上传文件(自动按类型归库)"
            onClick={() => fileRef.current?.click()} className="brain-nav__feed-upload">
            <Upload className="w-4 h-4" />
          </button>
        </div>
        <input ref={fileRef} type="file" multiple className="hidden"
          accept=".pdf,.docx,.doc,.txt,.md,.html,.htm,.png,.jpg,.jpeg,.gif,.webp,.bmp"
          onChange={(e) => { void pickFiles(e.target.files); e.target.value = ""; }} />
      </div>
    </aside>
  );
}

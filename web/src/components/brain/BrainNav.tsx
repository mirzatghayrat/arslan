import { useMemo, useRef, useState } from "react";
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
  onTagFilter: (tag: string) => void;
  onCreateNote?: () => void;
  onGenerate?: (topic: string) => void;
}

/** Second-Brain left column: a persistent navigator for the always-on graph.
 * Search + a tag explorer up top (clicking a chip focuses that tag cluster in the
 * graph), then a tidy multi-level collapsible tree (画像 grouped by category, 材料
 * by provenance); then create/generate/feed + a collapsed index-health strip.
 * Hovering a row focuses its graph node; clicking opens its detail in the right rail. */
export default function BrainNav({ branches, focusedId, onFocus, onPick, onChanged, onTagFilter, onCreateNote, onGenerate }: Props) {
  const [q, setQ] = useState("");
  const [feed, setFeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [topic, setTopic] = useState("");
  const [generating, setGenerating] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const ql = q.trim().toLowerCase();

  const toggle = (key: string) =>
    setCollapsed((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });

  const matches = (l: BrainLeaf) =>
    !ql || l.label.toLowerCase().includes(ql) || (l.tags ?? []).some((t) => t.toLowerCase().includes(ql))
    || (l.category ?? "").toLowerCase().includes(ql);

  // second-level sub-grouping: profile→category, material→provenance, else flat
  const subGroups = (b: BrainBranch): { key: string; label: string; leaves: BrainLeaf[] }[] | null => {
    if (b.kind !== "profile" && b.kind !== "material") return null;
    const field = (l: BrainLeaf) => b.kind === "profile" ? (l.category || "未分类") : (l.provenance || "其它");
    const map = new Map<string, BrainLeaf[]>();
    for (const l of b.children) (map.get(field(l)) ?? map.set(field(l), []).get(field(l))!).push(l);
    return [...map.entries()].map(([key, leaves]) => ({ key, label: key, leaves }));
  };

  // tag explorer = note tags ∪ fact category, with counts
  const tagChips = useMemo(() => {
    const counts = new Map<string, number>();
    for (const b of branches) for (const l of b.children) {
      const vals = b.kind === "note" ? (l.tags ?? []) : b.kind === "profile" && l.category ? [l.category] : [];
      for (const t of vals) counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [branches]);

  const Row = (l: BrainLeaf) => (
    <div key={l.ref} data-testid="brain-nav-row"
      className={`brain-nav__row${focusedId === l.ref ? " is-focused" : ""}`}
      onMouseEnter={() => onFocus(l.ref)} onMouseLeave={() => onFocus(null)} onClick={() => onPick(l)}>
      <span className="brain-nav__row-label">{l.label}</span>
      {l.usage_count ? <span className="brain-nav__row-usage">用过 {l.usage_count}</span> : null}
    </div>
  );

  const quickFeed = async () => {
    const t = feed.trim(); if (!t) return;
    setBusy(true); setErr(null);
    try { await feedTextOrUrl(t); setFeed(""); onChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const pickFiles = async (files: FileList | null) => {
    const list = Array.from(files ?? []); if (!list.length) return;
    setBusy(true); setErr(null); const failed: string[] = [];
    for (const f of list) { try { await feedFile(f); } catch { failed.push(f.name); } }
    setBusy(false); if (failed.length) setErr(`未识别/失败:${failed.join("、")}`); onChanged();
  };
  const runGenerate = async () => {
    const t = topic.trim(); if (!t || !onGenerate) return;
    setGenerating(true); try { onGenerate(t); setTopic(""); } finally { setGenerating(false); }
  };

  return (
    <aside className="brain-nav">
      <div className="brain-nav__search">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索笔记 / 标签 / 内容…"
          className="brain-nav__search-input" />
      </div>

      {tagChips.length > 0 && (
        <div className="brain-nav__tags">
          <div className="brain-nav__tags-head">标签</div>
          <div className="brain-nav__tags-chips">
            {tagChips.map(([t, c]) => (
              <button key={t} className={`brain-nav__chip${focusedId === `tag:${t.toLowerCase()}` ? " is-active" : ""}`}
                onClick={() => onTagFilter(t)}>
                #{t}<span className="brain-nav__chip-count">{c}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="brain-nav__tree">
        {branches.map((b) => {
          const open = !collapsed.has(b.kind) || ql !== "";
          const groups = subGroups(b);
          const flatKids = b.children.filter(matches);
          return (
            <div key={b.kind} className="brain-nav__branch">
              <div className="brain-nav__branch-head" onClick={() => toggle(b.kind)}>
                <span className="brain-nav__caret">{open ? "▾" : "▸"}</span>
                <span className="brain-nav__dot" style={{ background: hueVar(b.kind) }} />
                <span className="brain-nav__branch-label">{b.label}</span>
                <span className="brain-nav__count">{b.children.length}</span>
              </div>
              {open && groups
                ? groups.map((g) => {
                    const kids = g.leaves.filter(matches);
                    if (!kids.length) return null;
                    const gkey = `${b.kind}:${g.key}`;
                    const gopen = !collapsed.has(gkey) || ql !== "";
                    return (
                      <div key={gkey} className="brain-nav__group">
                        <div className="brain-nav__group-head" onClick={() => toggle(gkey)}>
                          <span className="brain-nav__caret">{gopen ? "▾" : "▸"}</span>
                          <span className="brain-nav__group-label">{g.label}</span>
                          <span className="brain-nav__count">{g.leaves.length}</span>
                        </div>
                        {gopen && kids.map(Row)}
                      </div>
                    );
                  })
                : open && flatKids.map(Row)}
              {open && !groups && flatKids.length === 0 && <div className="brain-nav__empty">暂无</div>}
            </div>
          );
        })}
      </div>

      {onCreateNote && (
        <div className="brain-nav__create">
          <button type="button" className="brain-nav__create-btn" onClick={onCreateNote}>＋ 新建笔记</button>
        </div>
      )}
      {onGenerate && (
        <div className="brain-nav__generate">
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="AI 主题生成笔记…"
            onKeyDown={(e) => { if (e.key === "Enter") void runGenerate(); }} className="brain-nav__generate-input" />
          <button type="button" disabled={generating || !topic.trim()} onClick={() => void runGenerate()}
            className="brain-nav__generate-btn">{generating ? "生成中…" : "生成"}</button>
        </div>
      )}

      <div className="brain-nav__feed">
        {err && <div className="brain-nav__err">{err}</div>}
        <input value={feed} onChange={(e) => setFeed(e.target.value)} placeholder="贴文本 / URL 快速投喂…"
          onKeyDown={(e) => { if (e.key === "Enter") void quickFeed(); }} className="brain-nav__feed-input" />
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

      <div className="brain-nav__health">
        <button className="brain-nav__health-toggle" onClick={() => setHealthOpen((v) => !v)}>
          <span className="brain-nav__caret">{healthOpen ? "▾" : "▸"}</span> 索引健康
        </button>
        {healthOpen && <BrainIndexHealth />}
      </div>
    </aside>
  );
}

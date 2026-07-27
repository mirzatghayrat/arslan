import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type BrainLeaf, type GraphNodeDto } from "../../api/client";
import { useBrainTree, recentIds } from "../../hooks/useBrainTree";
import { feedFile } from "../../lib/feed";
import BrainEntryDetail from "./BrainEntryDetail";
import BrainActivityStrip from "./BrainActivityStrip";
import BrainProposalInbox from "./BrainProposalInbox";
import BrainGraph from "./BrainGraph";
import BrainAsOfSlider from "./BrainAsOfSlider";
import BrainLineage from "./BrainLineage";
import BrainNav from "./BrainNav";
import NoteEditor from "./NoteEditor";

export default function BrainSection() {
  const { t } = useTranslation();
  const { branches, loading, error, refresh } = useBrainTree();
  const glowIds = useMemo(() => recentIds(branches), [branches]);
  const allLabels = useMemo(() => branches.flatMap((b) => b.children.map((l) => l.label)), [branches]);

  // 🔴 F0-2: `focusedId` used to be THREE things at once — the hover channel (Nav and
  // Graph both wrote it on mouseenter/mouseleave), the "lit cluster" input, and the tag
  // filter. Because hover cleared it on mouseleave, clicking a tag chip and then moving
  // the cursor over ANY node destroyed the filter. Split into the two real intents:
  //
  //   hoveredId  transient, cleared on mouseleave (unchanged behaviour)
  //   tagFilter  persistent until explicitly cleared
  //
  // `lit` is hover-wins-over-filter, so hovering still previews a cluster and the filter
  // survives underneath. The old mouseleave→null was also the de-facto way to escape a
  // filter, so an explicit clear affordance replaces it (see BrainNav's chip row).
  // F2: the memory-proposal inbox is a PEER surface, not a graph overlay — and it is a
  // different inbox from the evolution one under Diagnostics (different table, different
  // lifecycle, different actions). Kept behind a toggle so the graph stays the default
  // view rather than being pushed aside by a queue that is usually empty.
  const [showInbox, setShowInbox] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const lit = hoveredId ?? tagFilter;
  // bumped whenever something is written, so the graph refetches. It used to load once
  // on mount, so a note created in this session never appeared in it.
  const [graphKey, setGraphKey] = useState(0);
  const reloadAll = () => { refresh(); setGraphKey((k) => k + 1); };
  const [picked, setPicked] = useState<BrainLeaf | null>(null);
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [showTags, setShowTags] = useState(true);   // tag-node visibility, toggled from BrainNav's 标签 header
  // F1 — null = home = no filtering at all. Paint-time only: it never refetches and
  // never reaches what gets injected into a spawn.
  const [asOf, setAsOf] = useState<string | null>(null);
  const [graphNodes, setGraphNodes] = useState<GraphNodeDto[]>([]);

  // The graph is ALWAYS the main canvas; picking anything (tree row or graph node)
  // slides its detail in as the right rail over the graph — the graph stays visible.
  const pick = (l: BrainLeaf) => { if ((l.kind as string) === "ghost") return; setPicked(l); };

  // F1 — jumping along a genealogy. The lineage panel only knows node ids, so the
  // matching graph node supplies the leaf. A superseded ancestor is a legitimate
  // target: being replaced is exactly why you would click it.
  const pickById = (id: string) => {
    const n = graphNodes.find((g) => g.id === id);
    if (!n) return;
    pick({ kind: n.kind as BrainLeaf["kind"], ref: n.ref, label: n.label,
      provenance: null, confidence: n.confidence ?? null, usage_count: n.usage_count ?? 0,
      last_used_at: n.last_used_at ?? null, last_used_ref: null, value: n.val });
  };

  const createNoteWithTitle = async (title: string) => {
    const n = await api.createNote({ title });
    reloadAll();
    pick({ kind: "note", ref: `note:${n.id}`, label: n.title, provenance: t("brain.handwritten"),
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 });
  };
  const generateFromTopic = async (topic: string) => { await api.generateNotes(topic); reloadAll(); };
  // clicking a tag chip focuses that tag node in the graph → lights it + its whole
  // cluster (shared-tag members), dims the rest. Toggle off if already focused.
  const onTagFilter = (tag: string) => {
    const id = `tag:${tag.trim().toLowerCase()}`;
    setTagFilter((cur) => (cur === id ? null : id));
  };
  // Hiding tag nodes must also drop a tag filter: with the node gone the filter matches
  // nothing, and "matches nothing" would dim every node and edge — a black graph with no
  // explanation. (BrainGraph independently refuses to dim on an unresolvable id; this is
  // the state-side half, so the chip's active styling does not lie either.)
  const toggleTags = () => setShowTags((v) => { if (v) setTagFilter(null); return !v; });

  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const files = Array.from(e.dataTransfer?.files ?? []); if (!files.length) return;
    let ok = 0; const failed: string[] = [];
    for (const file of files) {
      setStatus(t("brain.feeding_progress", { i: ok + failed.length + 1, total: files.length }));
      try { await feedFile(file, t); ok += 1; } catch { failed.push(file.name); }
    }
    reloadAll();
    setStatus(failed.length ? t("brain.fed_partial", { n: ok, names: failed.join(", ") }) : t("brain.fed_ok", { n: ok }));
    setTimeout(() => setStatus(null), 4000);
  };

  return (
    <div data-dropzone="1" className="flex-1 flex h-full overflow-hidden relative"
      onDragOver={(e) => { if (hasFiles(e)) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
      onDrop={(e) => void onDrop(e)}>
      <BrainNav branches={branches} litId={lit} onHover={setHoveredId} onPick={pick} onChanged={reloadAll}
        onTagFilter={onTagFilter} activeTag={tagFilter} onClearTag={() => setTagFilter(null)}
        showTags={showTags} onToggleTags={toggleTags}
        onCreateNote={(title) => void createNoteWithTitle(title)}
        inboxOpen={showInbox} onToggleInbox={() => setShowInbox((v) => !v)}
        onGenerate={(t) => void generateFromTopic(t)} />

      <div className="flex-1 relative h-full overflow-hidden">
        {error
          ? <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-muted-foreground">{t("brain.graph_load_failed")}</div>
          : <BrainGraph litId={lit} onHover={setHoveredId} onPick={pick}
              onCreateNoteWithTitle={(t) => void createNoteWithTitle(t)} showTags={showTags}
              glowIds={glowIds} reloadKey={graphKey} asOf={asOf} onData={setGraphNodes}
              className="w-full h-full" />}
        {/* F1 — sits over the graph, above the activity strip. Renders nothing until the
            data spans more than one instant, so an empty or same-day brain is not given
            a control that cannot do anything. */}
        <BrainAsOfSlider nodes={graphNodes} value={asOf} onChange={setAsOf}
          className="absolute bottom-14 left-3 right-3 z-10 rounded bg-surface-raised/80 px-2 py-1.5 backdrop-blur" />
        {loading && <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-subtle-foreground uppercase tracking-widest pointer-events-none">loading…</div>}

        {/* picked entry slides in as the right rail OVER the graph (both are absolute right-0) */}
        {picked && picked.kind === "note" ? (
          <NoteEditor noteId={Number(picked.ref.split(":")[1])} onClose={() => setPicked(null)}
            onChanged={reloadAll} allLabels={allLabels}
            onOpenNote={(id, title) => pick({ kind: "note", ref: `note:${id}`, label: title,
              provenance: t("brain.handwritten"), confidence: null, usage_count: 0, last_used_at: null,
              last_used_ref: null, value: 1 })}
            onHover={setHoveredId} />
        ) : picked ? (
          // 🔴 The lineage goes INSIDE the detail panel, as a child. BrainEntryDetail's
          // own root is `absolute top-0 right-0 h-full … z-20` and opaque, so an
          // absolutely-positioned wrapper around both made the detail its containing
          // block: the panel covered the lineage completely and the whole genealogy was
          // unreachable in the app while its component tests passed. Component-level
          // tests render it standalone and cannot see this — hence the BrainSection
          // test added alongside this fix.
          <BrainEntryDetail leaf={picked} onClose={() => setPicked(null)} onChanged={reloadAll}>
            <BrainLineage selectedId={picked.ref} nodes={graphNodes} onPickId={pickById}
              className="mt-3 border-t border-border pt-2" />
          </BrainEntryDetail>
        ) : null}
        {showInbox && (
          <div className="absolute top-0 right-0 h-full w-[400px] bg-surface-raised border-l border-border overflow-auto z-20">
            <BrainProposalInbox onChanged={reloadAll} />
          </div>
        )}
        <BrainActivityStrip litId={lit} onHover={setHoveredId} onPick={pick} reloadKey={graphKey} />
      </div>

      {status && <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 text-[12px] px-3 py-1.5 rounded-lg bg-surface border border-border text-foreground">{status}</div>}
      {dragging && (
        <div data-drop-overlay="1" className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none bg-primary/[0.10] border-2 border-dashed border-primary rounded-2xl">
          <div className="text-[15px] font-medium text-primary">{t("brain.drop_to_feed")}</div>
        </div>
      )}
    </div>
  );
}

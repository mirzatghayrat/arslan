import { useEffect, useMemo, useRef, useState } from "react";
import type { TreeNode } from "../../hooks/useKnowledgeTree";
import { familyIds, layoutSegments, type Segment } from "./sunburstLayout";
import { hueVar } from "./hues";

interface Props { tree: TreeNode; focusedId: string | null; onFocus: (id: string | null) => void; className?: string; }

const CX = 310, CY = 310;
const LAYOUT = { cx: CX, cy: CY, innerR: 66, outerR: 300, bandR: 9, padAngle: 0.0015, topMinFrac: 0.07, gapAngle: 0.175 };

function findNode(n: TreeNode, id: string): TreeNode | null {
  if (n.id === id) return n;
  for (const c of n.children ?? []) { const r = findNode(c, id); if (r) return r; }
  return null;
}
function pathTo(n: TreeNode, id: string, acc: TreeNode[] = []): TreeNode[] | null {
  const next = [...acc, n];
  if (n.id === id) return next;
  for (const c of n.children ?? []) { const r = pathTo(c, id, next); if (r) return r; }
  return null;
}

/** Root view: depth 1 = neutral thin top band, depth>=2 = the group's hue brightening
 * toward white outward. Drilled view (atRoot=false): color from depth 1, since there's
 * no top-category band to delineate. cd = colored-ring index (0 = innermost colored). */
function fillFor(node: { kind: string; cat: string; hueKey?: string; fileType?: string }, depth: number, atRoot: boolean): string {
  if (atRoot && depth <= 1) return "color-mix(in srgb, var(--muted-foreground) 22%, var(--surface))"; // faint band
  const key = node.fileType ? `ft:${node.fileType}` : (node.hueKey ?? node.cat);
  const cd = atRoot ? depth - 2 : depth - 1;             // 0 at innermost colored ring
  const lighten = Math.min(12 + cd * 20, 68);            // % white, brighter outward
  return `color-mix(in srgb, ${hueVar(key)} ${100 - lighten}%, white ${lighten}%)`;
}

/** Native mouseenter/mouseleave listeners (not React's synthetic onMouseEnter/Leave,
 * which are backed by bubbling mouseover/mouseout and never fire for a real, non-bubbling
 * mouseenter/mouseleave pair) so hover-to-focus reacts to genuine pointer transitions. */
function SegmentPath({ s, dim, atRoot, onFocus, onClick }: { s: Segment; dim: boolean; atRoot: boolean; onFocus: (id: string | null) => void; onClick?: () => void }) {
  const ref = useRef<SVGPathElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const enter = () => onFocus(s.id);
    const leave = () => onFocus(null);
    el.addEventListener("mouseenter", enter);
    el.addEventListener("mouseleave", leave);
    return () => { el.removeEventListener("mouseenter", enter); el.removeEventListener("mouseleave", leave); };
  }, [s.id, onFocus]);

  return (
    <path ref={ref} data-node={s.id} data-dim={dim ? "1" : "0"} d={s.d} onClick={onClick}
      style={{ fill: fillFor(s, s.depth, atRoot), stroke: "white", strokeOpacity: 0.85, strokeWidth: 1.25,
        strokeLinejoin: "round", cursor: "pointer", opacity: dim ? 0.22 : 1,
        transition: "opacity .14s, fill .12s" }}>
      <title>{s.full ?? s.name}</title>
    </path>
  );
}

export default function KnowledgeSunburst({ tree, focusedId, onFocus, className }: Props) {
  const [rootId, setRootId] = useState("root");
  const viewRoot = useMemo(() => findNode(tree, rootId) ?? tree, [tree, rootId]);
  const atRoot = viewRoot.id === "root";
  const crumbs = useMemo(() => pathTo(tree, viewRoot.id) ?? [tree], [tree, viewRoot.id]);
  const segs = useMemo(() => layoutSegments(viewRoot, { ...LAYOUT, band: atRoot }), [viewRoot, atRoot]);
  const fam = useMemo(() => familyIds(viewRoot, focusedId), [viewRoot, focusedId]);
  const items = useMemo(() => leafCount(viewRoot), [viewRoot]);

  return (
    <div className={className} style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
      <div style={{ position: "absolute", top: 12, left: 14, display: "flex", gap: 6, fontSize: 11, color: "var(--muted-foreground)", flexWrap: "wrap", maxWidth: "60%", zIndex: 2 }}>
        {crumbs.map((c, i) => (
          <span key={c.id} data-breadcrumb={c.id === "root" ? "root" : c.id}
            onClick={() => setRootId(c.id)}
            style={{ cursor: "pointer", opacity: i === crumbs.length - 1 ? 1 : 0.65 }}>
            {c.id === "root" ? "YOU" : c.name}{i < crumbs.length - 1 ? " ›" : ""}
          </span>
        ))}
      </div>
      <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg viewBox="0 0 620 620" style={{ width: "min(560px,70vh)", height: "auto" }} role="img" aria-label="第二大脑同心扇形,悬停联动">
          {segs.map((s) => {
            const hasKids = (findNode(viewRoot, s.id)?.children?.length ?? 0) > 0;
            return (
              <SegmentPath key={s.id} s={s} dim={focusedId != null && !fam.has(s.id)} atRoot={atRoot}
                onFocus={onFocus} onClick={hasKids ? () => setRootId(s.id) : undefined} />
            );
          })}
          <circle cx={CX} cy={CY} r={62}
            onClick={() => { if (crumbs.length > 1) setRootId(crumbs[crumbs.length - 2].id); }}
            style={{ fill: "var(--surface)", stroke: "var(--hub)", strokeOpacity: 0.4, strokeWidth: 1.6, cursor: "pointer" }} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", pointerEvents: "none", textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--muted-foreground)", marginBottom: 7 }}>整个第二大脑</div>
          <div style={{ fontSize: 34, fontWeight: 600, color: "var(--foreground)", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{viewRoot.value}<span style={{ fontSize: 14, fontWeight: 400, color: "var(--muted-foreground)", marginLeft: 5 }}>块</span></div>
          <div style={{ fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: 10.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted-foreground)", marginTop: 8 }}>{items} 项 · {(viewRoot.children ?? []).length} 分类</div>
        </div>
      </div>
    </div>
  );
}

function leafCount(n: TreeNode): number {
  return n.children && n.children.length ? n.children.reduce((s, c) => s + leafCount(c), 0) : 1;
}

import { useEffect, useMemo, useRef } from "react";
import type { TreeNode } from "../../hooks/useKnowledgeTree";
import { familyIds, layoutSegments, type Segment } from "./sunburstLayout";
import { hueVar } from "./hues";

interface Props { tree: TreeNode; focusedId: string | null; onFocus: (id: string | null) => void; className?: string; }

const CX = 310, CY = 310;
const LAYOUT = { cx: CX, cy: CY, innerR: 66, outerR: 300, bandR: 9, padAngle: 0.012 };

/** depth 1 = neutral thin top band; depth>=2 = the group's hue, brightening toward
 * white the further out it sits (cd = colored-ring index). No mixing toward --surface. */
function fillFor(node: { kind: string; cat: string; hueKey?: string; fileType?: string }, depth: number): string {
  if (depth <= 1) return "color-mix(in srgb, var(--muted-foreground) 22%, var(--surface))"; // faint band
  const key = node.fileType ? `ft:${node.fileType}` : (node.hueKey ?? node.cat);
  const cd = depth - 2;                                  // 0 at innermost colored ring
  const lighten = Math.min(12 + cd * 20, 68);            // % white, brighter outward
  return `color-mix(in srgb, ${hueVar(key)} ${100 - lighten}%, white ${lighten}%)`;
}

/** Native mouseenter/mouseleave listeners (not React's synthetic onMouseEnter/Leave,
 * which are backed by bubbling mouseover/mouseout and never fire for a real, non-bubbling
 * mouseenter/mouseleave pair) so hover-to-focus reacts to genuine pointer transitions. */
function SegmentPath({ s, dim, onFocus }: { s: Segment; dim: boolean; onFocus: (id: string | null) => void }) {
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
    <path ref={ref} data-node={s.id} data-dim={dim ? "1" : "0"} d={s.d}
      style={{ fill: fillFor(s, s.depth), stroke: "var(--surface)", strokeWidth: 0.5,
        strokeLinejoin: "round", cursor: "pointer", opacity: dim ? 0.22 : 1,
        transition: "opacity .14s, fill .12s" }}>
      <title>{s.full ?? s.name}</title>
    </path>
  );
}

export default function KnowledgeSunburst({ tree, focusedId, onFocus, className }: Props) {
  const segs = useMemo(() => layoutSegments(tree, LAYOUT), [tree]);
  const fam = useMemo(() => familyIds(tree, focusedId), [tree, focusedId]);
  const items = useMemo(() => leafCount(tree), [tree]);

  return (
    <div className={className} style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <svg viewBox="0 0 620 620" style={{ width: "min(560px,70vh)", height: "auto" }} role="img" aria-label="第二大脑同心扇形,悬停联动">
        {segs.map((s) => (
          <SegmentPath key={s.id} s={s} dim={focusedId != null && !fam.has(s.id)} onFocus={onFocus} />
        ))}
        <circle cx={CX} cy={CY} r={62} style={{ fill: "var(--surface)", stroke: "var(--hub)", strokeOpacity: 0.4, strokeWidth: 1.6 }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", pointerEvents: "none", textAlign: "center" }}>
        <div style={{ fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--muted-foreground)", marginBottom: 7 }}>整个第二大脑</div>
        <div style={{ fontSize: 34, fontWeight: 600, color: "var(--foreground)", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{tree.value}<span style={{ fontSize: 14, fontWeight: 400, color: "var(--muted-foreground)", marginLeft: 5 }}>块</span></div>
        <div style={{ fontFamily: "var(--font-mono, ui-monospace, monospace)", fontSize: 10.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted-foreground)", marginTop: 8 }}>{items} 项 · {(tree.children ?? []).length} 分类</div>
      </div>
    </div>
  );
}

function leafCount(n: TreeNode): number {
  return n.children && n.children.length ? n.children.reduce((s, c) => s + leafCount(c), 0) : 1;
}

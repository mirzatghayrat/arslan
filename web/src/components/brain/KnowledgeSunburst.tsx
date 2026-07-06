import { useEffect, useMemo, useRef } from "react";
import type { TreeNode, Cat } from "../../hooks/useKnowledgeTree";
import { familyIds, layoutSegments, type Segment } from "./sunburstLayout";

interface Props { tree: TreeNode; focusedId: string | null; onFocus: (id: string | null) => void; className?: string; }

const TOKEN: Record<Cat, string> = { collection: "--success", spawn: "--primary", pref: "--danger" };
const SRC = "--info";
const RINGS: (null | [number, number])[] = [null, [70, 150], [156, 224], [230, 296]];
const CX = 310, CY = 310;

function fillFor(cat: Cat, kind: string, depth: number, focused: boolean): string {
  const tok = kind === "source" ? SRC : TOKEN[cat];
  const mix = depth <= 1 ? 100 : depth === 2 ? 82 : 66;
  if (focused) return `color-mix(in srgb, color-mix(in srgb, var(${tok}) ${mix}%, var(--surface)) 86%, var(--foreground))`;
  return `color-mix(in srgb, var(${tok}) ${mix}%, var(--surface))`;
}

/** Native mouseenter/mouseleave listeners (not React's synthetic onMouseEnter/Leave,
 * which are backed by bubbling mouseover/mouseout and never fire for a real, non-bubbling
 * mouseenter/mouseleave pair) so hover-to-focus reacts to genuine pointer transitions. */
function SegmentPath({ s, focused, onFocus }: { s: Segment; focused: boolean; onFocus: (id: string | null) => void }) {
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
    <path ref={ref} data-node={s.id} data-focus={focused ? "1" : "0"} d={s.d}
      style={{ fill: fillFor(s.cat, s.kind, s.depth, focused), stroke: focused ? "var(--foreground)" : "var(--background)",
        strokeWidth: 1.6, strokeLinejoin: "round", cursor: "pointer", transition: "fill .12s, stroke .12s" }} />
  );
}

export default function KnowledgeSunburst({ tree, focusedId, onFocus, className }: Props) {
  const segs = useMemo(() => layoutSegments(tree, { cx: CX, cy: CY, rings: RINGS }), [tree]);
  const fam = useMemo(() => familyIds(tree, focusedId), [tree, focusedId]);
  const items = useMemo(() => leafCount(tree), [tree]);

  return (
    <div className={className} style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <svg viewBox="0 0 620 620" style={{ width: "min(560px,70vh)", height: "auto" }} role="img" aria-label="第二大脑同心扇形,悬停联动">
        {segs.map((s) => (
          <SegmentPath key={s.id} s={s} focused={fam.has(s.id)} onFocus={onFocus} />
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

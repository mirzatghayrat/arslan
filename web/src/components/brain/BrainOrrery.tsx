import { useEffect, useRef } from "react";
import type { BrainBranch, BrainLeaf } from "../../api/client";
import { hueVar } from "./hues";

interface Props {
  branches: BrainBranch[];
  focusedId: string | null;
  onFocus: (id: string | null) => void;
  onPick: (leaf: BrainLeaf) => void;
  glowIds?: Set<string>;
  className?: string;
}

const CX = 280;
const CY = 280;
// One orbit ring per type, inner → outer. Profile (usually the most entries) sits
// outermost where the circumference gives its many dots room to breathe.
const RING: Record<string, number> = { material: 104, learning: 166, profile: 232 };
const RING_ORDER: BrainBranch["kind"][] = ["material", "learning", "profile"];

function dotR(value: number): number {
  // value = content weight + usage (from /brain/tree). sqrt-tempered so a heavy
  // node grows but never dwarfs the field.
  return Math.max(2.6, Math.min(9, 2.6 + Math.sqrt(Math.max(0, value)) * 0.95));
}

/** A real star map: the center is YOU, each content type is an orbit ring, and
 * every piece of knowledge is a dot on its ring — size = usage/weight, colour =
 * type, a soft glow marks what was used recently. Hovering a dot focuses it
 * (shared focusedId with the nav); clicking opens its detail. */
export default function BrainOrrery({ branches, focusedId, onFocus, onPick, glowIds, className }: Props) {
  const byKind = new Map(branches.map((b) => [b.kind, b]));

  return (
    <div className={className} style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
      <div style={{ position: "absolute", top: 12, left: 14, fontSize: 11, color: "var(--muted-foreground)", zIndex: 2 }}>YOU</div>
      <svg viewBox="0 0 560 560" style={{ width: "min(560px, 72vh)", height: "auto" }} role="img" aria-label="第二大脑星图:三类轨道,每条知识一个光点">
        {/* faint orbit rings */}
        {RING_ORDER.map((kind) => (
          <circle key={`ring-${kind}`} cx={CX} cy={CY} r={RING[kind]} fill="none"
            stroke="color-mix(in srgb, var(--foreground) 11%, transparent)"
            strokeWidth={1} strokeDasharray="1.5 5" />
        ))}
        {/* type labels at each ring's top */}
        {RING_ORDER.map((kind) => {
          const b = byKind.get(kind);
          if (!b) return null;
          return (
            <text key={`lbl-${kind}`} x={CX} y={CY - RING[kind] - 8} textAnchor="middle"
              fontSize={11} fontWeight={500} fill={hueVar(kind)} style={{ letterSpacing: "0.02em" }}>
              {b.label} · {b.children.length}
            </text>
          );
        })}
        {/* center glow + YOU core */}
        <circle cx={CX} cy={CY} r={46} fill="var(--primary)" opacity={0.09} />
        <circle cx={CX} cy={CY} r={22} fill="var(--surface)" stroke="var(--primary)" strokeWidth={1.4} />
        <text x={CX} y={CY + 4} textAnchor="middle" fontSize={11} fontFamily="var(--font-mono, monospace)" fill="var(--muted-foreground)">YOU</text>
        {/* dots */}
        {RING_ORDER.flatMap((kind) => {
          const b = byKind.get(kind);
          if (!b) return [];
          const r = RING[kind];
          const n = b.children.length;
          return b.children.map((leaf, i) => {
            const ang = (-90 + (i * 360) / Math.max(1, n)) * (Math.PI / 180);
            const x = CX + r * Math.cos(ang);
            const y = CY + r * Math.sin(ang);
            const focused = focusedId === leaf.ref;
            const dim = focusedId != null && !focused;
            const glow = glowIds?.has(leaf.ref) ?? false;
            const rad = dotR(leaf.value) * (focused ? 1.5 : 1);
            return (
              <Dot key={leaf.ref} x={x} y={y} r={rad} color={hueVar(kind)}
                focused={focused} dim={dim} glow={glow}
                title={`${leaf.label}${leaf.usage_count ? ` · 用过 ${leaf.usage_count}` : ""}`}
                onEnter={() => onFocus(leaf.ref)} onLeave={() => onFocus(null)}
                onClick={() => onPick(leaf)} />
            );
          });
        })}
      </svg>
    </div>
  );
}

function Dot({ x, y, r, color, focused, dim, glow, title, onEnter, onLeave, onClick }: {
  x: number; y: number; r: number; color: string; focused: boolean; dim: boolean; glow: boolean;
  title: string; onEnter: () => void; onLeave: () => void; onClick: () => void;
}) {
  // native listeners so a real mouseenter/leave pair drives focus reliably
  const ref = useRef<SVGCircleElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.addEventListener("mouseenter", onEnter);
    el.addEventListener("mouseleave", onLeave);
    return () => { el.removeEventListener("mouseenter", onEnter); el.removeEventListener("mouseleave", onLeave); };
  }, [onEnter, onLeave]);
  return (
    <circle ref={ref} cx={x} cy={y} r={r} fill={color} onClick={onClick}
      style={{
        cursor: "pointer",
        opacity: dim ? 0.25 : 1,
        stroke: focused ? "white" : "none",
        strokeWidth: focused ? 1.5 : 0,
        filter: glow ? "drop-shadow(0 0 5px var(--primary))" : undefined,
        transition: "opacity .14s, r .12s",
      }}>
      <title>{title}</title>
    </circle>
  );
}

import { useEffect, useRef, useState } from "react";
import { type NodeState, patternFor } from "./nodeBarSequences";

const FRAME_MS = 180; // matches FRAME_DURATION_MS in make_arslan_node_bar_gif.py

const ACTIVE = "#FF8E24"; // brand orange
const INACTIVE = "#785C3E"; // brand dim — reads as "off" on the dark gradient
const EDGE = "#785C3E";

// viewBox geometry: three nodes in a row — left —— hub —— right.
const NODES = [
  { x: 14, r: 7 },
  { x: 60, r: 7 },
  { x: 106, r: 7 },
] as const;
const CY = 16;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export default function NodeBar({
  state,
  className = "h-6 w-[72px]",
}: {
  state: NodeState;
  className?: string;
}) {
  const reduced = prefersReducedMotion();
  const [frame, setFrame] = useState(0);
  const reducedRef = useRef(reduced);
  reducedRef.current = reduced;

  // Restart the animation cleanly whenever the state changes.
  useEffect(() => {
    setFrame(0);
    if (reducedRef.current) return; // static — no interval under reduced motion
    const id = window.setInterval(() => setFrame((f) => f + 1), FRAME_MS);
    return () => window.clearInterval(id);
  }, [state]);

  const pattern = patternFor(state, frame);

  return (
    <svg
      className={className}
      viewBox="0 0 120 32"
      fill="none"
      role="img"
      aria-hidden
    >
      {/* connecting edges (constant, subtle) */}
      <line x1={NODES[0].x} y1={CY} x2={NODES[1].x} y2={CY} stroke={EDGE} strokeWidth={3} strokeLinecap="round" />
      <line x1={NODES[1].x} y1={CY} x2={NODES[2].x} y2={CY} stroke={EDGE} strokeWidth={3} strokeLinecap="round" />
      {/* nodes light up per the ported sequence */}
      {NODES.map((n, i) => {
        const on = pattern[i] === "on";
        return (
          <circle
            key={i}
            cx={n.x}
            cy={CY}
            r={n.r}
            fill={on ? ACTIVE : INACTIVE}
            style={on ? { filter: "drop-shadow(0 0 3px rgba(255,142,36,0.7))" } : undefined}
          />
        );
      })}
    </svg>
  );
}

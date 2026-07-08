import { useEffect, useMemo, useRef, useState } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import { select } from "d3-selection";
import { drag as d3drag } from "d3-drag";
import { zoom as d3zoom } from "d3-zoom";
import { api, type BrainLeaf, type BrainGraphDto } from "../../api/client";
import { hueVar } from "./hues";

interface Props {
  focusedId: string | null;
  onFocus: (id: string | null) => void;
  onPick: (leaf: BrainLeaf) => void;
  glowIds?: Set<string>;
  className?: string;
}
const W = 620, H = 560;

export default function BrainGraph({ focusedId, onFocus, onPick, glowIds, className }: Props) {
  const [data, setData] = useState<BrainGraphDto | null>(null);
  // Nodes/links live in STATE (not refs) — the sim mutates these exact objects'
  // x/y in place, and the tick counter forces a re-render that reads them.
  const [nodes, setNodes] = useState<any[]>([]);
  const [links, setLinks] = useState<any[]>([]);
  const [, tick] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);

  useEffect(() => { let ok = true; api.getBrainGraph().then((d) => ok && setData(d)).catch(() => ok && setData({ nodes: [], links: [] })); return () => { ok = false; }; }, []);

  // neighbor map for hover highlight
  const neighbors = useMemo(() => {
    const map = new Map<string, Set<string>>();
    (data?.links ?? []).forEach((l) => {
      const s = String((l as any).source), t = String((l as any).target);
      (map.get(s) ?? map.set(s, new Set()).get(s)!).add(t);
      (map.get(t) ?? map.set(t, new Set()).get(t)!).add(s);
    });
    return map;
  }, [data]);

  useEffect(() => {
    if (!data) return;
    const ns = data.nodes.map((n) => ({ ...n }));
    const ls = data.links.map((l) => ({ ...l }));
    setNodes(ns); setLinks(ls);
    const sim = forceSimulation(ns as any)
      .force("link", forceLink(ls as any).id((d: any) => d.id).distance(70).strength(0.6))
      .force("charge", forceManyBody().strength(-160))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide((d: any) => 4 + Math.sqrt(d.val) * 2 + 4))
      .on("tick", () => tick((x) => x + 1));
    // zoom/pan on the group
    if (svgRef.current && gRef.current) {
      select(svgRef.current).call(d3zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 3])
        .on("zoom", (e) => { if (gRef.current) gRef.current.setAttribute("transform", e.transform.toString()); }) as any);
    }
    return () => { sim.stop(); };
  }, [data]);

  // drag handler attached to node circles via ref effect (use d3drag on each circle)
  const bindDrag = (el: SVGCircleElement | null, node: any) => {
    if (!el) return;
    select(el).call(d3drag<SVGCircleElement, unknown>()
      .on("start", () => { node.fx = node.x; node.fy = node.y; })
      .on("drag", (e) => { node.fx = e.x; node.fy = e.y; tick((x) => x + 1); })
      .on("end", () => { node.fx = null; node.fy = null; }) as any);
  };

  const nbr = focusedId ? neighbors.get(focusedId) : null;
  return (
    <div className={className} style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <svg ref={svgRef} data-testid="brain-graph" viewBox={`0 0 ${W} ${H}`} style={{ width: "min(620px,72vh)", height: "auto" }} role="img" aria-label="第二大脑关系图">
        <g ref={gRef}>
          {links.map((l: any, i) => (
            <line key={i} data-link x1={l.source?.x ?? 0} y1={l.source?.y ?? 0} x2={l.target?.x ?? 0} y2={l.target?.y ?? 0}
              stroke="color-mix(in srgb, var(--foreground) 14%, transparent)"
              strokeWidth={1} strokeDasharray={l.type === "provenance" ? "3 3" : undefined} />
          ))}
          {nodes.map((n: any) => {
            const dim = focusedId != null && focusedId !== n.id && !(nbr?.has(n.id));
            const r = Math.max(3, 3 + Math.sqrt(n.val) * 2) * (focusedId === n.id ? 1.5 : 1);
            const ghost = n.kind === "ghost";
            return (
              <g key={n.id} style={{ opacity: dim ? 0.2 : 1 }}>
                <circle ref={(el) => bindDrag(el, n)} data-node data-kind={n.kind}
                  cx={n.x ?? 0} cy={n.y ?? 0} r={r}
                  fill={ghost ? "transparent" : hueVar(n.kind)}
                  stroke={ghost ? "var(--muted-foreground)" : (focusedId === n.id ? "white" : "none")}
                  strokeDasharray={ghost ? "2 2" : undefined} strokeWidth={ghost ? 1 : (focusedId === n.id ? 1.5 : 0)}
                  onMouseEnter={() => onFocus(n.id)} onMouseLeave={() => onFocus(null)}
                  onClick={() => n.kind !== "ghost" && onPick({ kind: n.kind as BrainLeaf["kind"], ref: n.ref, label: n.label, provenance: null, confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: n.val })}
                  style={{ cursor: "pointer", filter: glowIds?.has(n.id) ? "drop-shadow(0 0 5px var(--primary))" : undefined }}>
                  <title>{n.label}</title>
                </circle>
                <text x={n.x ?? 0} y={(n.y ?? 0) - r - 3} textAnchor="middle" fontSize={9} fill="var(--muted-foreground)" style={{ pointerEvents: "none" }}>
                  {String(n.label).slice(0, 10)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

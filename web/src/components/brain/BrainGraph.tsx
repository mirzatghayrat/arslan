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
  onCreateNoteWithTitle: (title: string) => void;
  showTags: boolean;   // tag-node show/hide, driven from the left nav's 标签 header
  glowIds?: Set<string>;
  className?: string;
}
const W = 760, H = 620;
const CHARGE = -160, DISTANCE = 70;   // fixed physics (tuning sliders removed)

export default function BrainGraph({ focusedId, onFocus, onPick, onCreateNoteWithTitle, showTags, glowIds, className }: Props) {
  const [data, setData] = useState<BrainGraphDto | null>(null);
  const [nodes, setNodes] = useState<any[]>([]);
  const [links, setLinks] = useState<any[]>([]);
  const [, tick] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const simRef = useRef<any>(null);

  useEffect(() => { let ok = true; api.getBrainGraph().then((d) => ok && setData(d)).catch(() => ok && setData({ nodes: [], links: [] })); return () => { ok = false; }; }, []);

  // filtered view: hide tag nodes (+ their edges) when showTags is off
  const view = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    if (showTags) return data;
    const drop = new Set(data.nodes.filter((n) => n.kind === "tag").map((n) => n.id));
    return {
      nodes: data.nodes.filter((n) => !drop.has(n.id)),
      links: data.links.filter((l) => !drop.has(String(l.source)) && !drop.has(String(l.target))),
    };
  }, [data, showTags]);

  // degree map (for size) + neighbor map (for hover highlight)
  const { degree, neighbors } = useMemo(() => {
    const deg = new Map<string, number>();
    const nb = new Map<string, Set<string>>();
    view.links.forEach((l) => {
      const s = String((l as any).source?.id ?? l.source), t = String((l as any).target?.id ?? l.target);
      deg.set(s, (deg.get(s) ?? 0) + 1); deg.set(t, (deg.get(t) ?? 0) + 1);
      (nb.get(s) ?? nb.set(s, new Set()).get(s)!).add(t);
      (nb.get(t) ?? nb.set(t, new Set()).get(t)!).add(s);
    });
    return { degree: deg, neighbors: nb };
  }, [view]);

  useEffect(() => {
    if (!data) return;
    const ns = view.nodes.map((n) => ({ ...n }));
    const ls = view.links.map((l) => ({ ...l }));
    setNodes(ns); setLinks(ls);
    const sim = forceSimulation(ns as any)
      .force("link", forceLink(ls as any).id((d: any) => d.id).distance(DISTANCE).strength(0.55))
      .force("charge", forceManyBody().strength(CHARGE))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide((d: any) => 4 + Math.sqrt(d.val) * 2 + 6))
      .on("tick", () => tick((x) => x + 1));
    simRef.current = sim;
    if (svgRef.current && gRef.current) {
      const z = d3zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 4])
        .on("zoom", (e) => { if (gRef.current) gRef.current.setAttribute("transform", e.transform.toString()); });
      // d3-zoom binds its own native dblclick.zoom handler on the <svg> that calls
      // stopImmediatePropagation, which swallows the event before it bubbles to
      // React's root listener — breaking ghost-node double-click-to-create. Disable
      // d3's built-in double-click-to-zoom-in since we repurpose double-click.
      select(svgRef.current).call(z as any).on("dblclick.zoom", null);
    }
    return () => { sim.stop(); };
  }, [view, data]);   // eslint-disable-line react-hooks/exhaustive-deps

  const radius = (n: any) => {
    if (n.kind === "self") return 16;
    return Math.max(3.5, 3.5 + Math.sqrt(degree.get(n.id) ?? 0) * 2.4);
  };

  const bindDrag = (el: SVGCircleElement | null, node: any) => {
    if (!el) return;
    select(el).call(d3drag<SVGCircleElement, unknown>()
      .on("start", () => { simRef.current?.alphaTarget(0.3).restart(); node.fx = node.x; node.fy = node.y; })
      .on("drag", (e) => { node.fx = e.x; node.fy = e.y; })
      .on("end", () => { simRef.current?.alphaTarget(0); node.fx = null; node.fy = null; }) as any);
  };

  const nbr = focusedId ? neighbors.get(focusedId) : null;
  const isLit = (l: any) => {
    const s = String(l.source?.id ?? l.source), t = String(l.target?.id ?? l.target);
    return focusedId != null && (s === focusedId || t === focusedId);
  };

  return (
    <div className={className} style={{ height: "100%", position: "relative" }}>
      <svg ref={svgRef} data-testid="brain-graph" viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "100%", cursor: "grab" }} role="img" aria-label="第二大脑关系图">
        <g ref={gRef}>
          {links.map((l: any, i) => (
            <line key={i} data-link
              x1={l.source?.x ?? 0} y1={l.source?.y ?? 0} x2={l.target?.x ?? 0} y2={l.target?.y ?? 0}
              stroke={isLit(l) ? "var(--primary)" : "color-mix(in srgb, var(--foreground) 12%, transparent)"}
              strokeOpacity={focusedId != null && !isLit(l) ? 0.25 : 1}
              strokeWidth={isLit(l) ? 1.6 : 1}
              strokeDasharray={l.type === "provenance" ? "3 3" : undefined} />
          ))}
          {nodes.map((n: any) => {
            const dim = focusedId != null && focusedId !== n.id && !(nbr?.has(n.id));
            const r = radius(n);
            const ghost = n.kind === "ghost", self = n.kind === "self", tag = n.kind === "tag";
            const focused = focusedId === n.id;
            const fill = ghost ? "transparent" : self ? "var(--primary)" : hueVar(tag ? n.label : n.kind);
            return (
              <g key={n.id} style={{ opacity: dim ? 0.2 : 1, transition: "opacity 200ms" }}>
                {(focused || self) && (
                  <circle cx={n.x ?? 0} cy={n.y ?? 0} r={r + 6} fill="none"
                    stroke="var(--primary)" strokeOpacity={0.6} strokeWidth={2}
                    style={{ filter: "drop-shadow(0 0 8px var(--primary))", animation: "brainPulse 1.8s ease-in-out infinite" }} />
                )}
                <circle ref={(el) => bindDrag(el, n)} data-node data-kind={n.kind}
                  cx={n.x ?? 0} cy={n.y ?? 0} r={r} fill={fill}
                  stroke={ghost ? "var(--danger)" : focused ? "white" : self ? "white" : "none"}
                  strokeDasharray={ghost ? "2 2" : undefined}
                  strokeWidth={ghost ? 1 : focused || self ? 1.5 : 0}
                  onMouseEnter={(e) => { onFocus(n.id); (e.currentTarget as SVGElement).style.transform = "scale(1.3)"; }}
                  onMouseLeave={(e) => { onFocus(null); (e.currentTarget as SVGElement).style.transform = "scale(1)"; }}
                  onClick={() => { if (!ghost && !self && !tag) onPick({ kind: n.kind as BrainLeaf["kind"], ref: n.ref, label: n.label, provenance: null, confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: n.val }); }}
                  onDoubleClick={() => { if (ghost) onCreateNoteWithTitle(n.label); }}
                  style={{ cursor: ghost || self || tag ? "default" : "pointer", transformOrigin: "center", transformBox: "fill-box", transition: "transform 180ms", filter: glowIds?.has(n.id) ? "drop-shadow(0 0 5px var(--primary))" : undefined }}>
                  <title>{n.label}</title>
                </circle>
                {/* No always-on labels — every node (你 included) reveals its name
                    only on hover/focus; the left tree names the rest. */}
                {focused && (
                  <text x={n.x ?? 0} y={(n.y ?? 0) - r - 3} textAnchor="middle" fontSize={self ? 11 : 9}
                    fontWeight={700} fill="var(--foreground)" style={{ pointerEvents: "none" }}>
                    {tag ? `#${n.label}` : String(n.label).slice(0, 16)}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      <div className="absolute bottom-2 left-2 z-10 rounded bg-surface-raised/70 px-2 py-1 font-mono text-[9px] text-subtle-foreground backdrop-blur">
        拖拽整理 · 双击幽灵点生成笔记 · 滚轮缩放
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import { select } from "d3-selection";
import { drag as d3drag } from "d3-drag";
import { zoom as d3zoom } from "d3-zoom";
import { api, type BrainLeaf, type BrainGraphDto, type GraphNodeDto, type GraphLinkDto } from "../../api/client";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { hueVar } from "./hues";

/** d3-force MUTATES the objects it is given: it adds x/y/vx/vy and REPLACES each link's
 * string endpoints with node references. The state used to be `any[]`, which meant every
 * field this component reads was unchecked — the D-round additions (usage_count,
 * sensitive, provenance_record) could be misspelled with no compile error. These types
 * say exactly what d3 leaves behind, so the DTO fields stay checked. */
type SimNode = GraphNodeDto & { x?: number; y?: number; fx?: number | null; fy?: number | null };
type SimLink = Omit<GraphLinkDto, "source" | "target"> & {
  source: string | SimNode;
  target: string | SimNode;
};

interface Props {
  /** the id whose cluster is lit — hover wins while hovering, the tag filter persists
   * underneath (see BrainSection). Renamed from `focusedId` because it is no longer only
   * about focus: it carries two different intents that used to fight each other. */
  litId: string | null;
  onHover: (id: string | null) => void;
  onPick: (leaf: BrainLeaf) => void;
  onCreateNoteWithTitle: (title: string) => void;
  showTags: boolean;   // tag-node show/hide, driven from the left nav's 标签 header
  glowIds?: Set<string>;
  /** bump to refetch. The graph used to load exactly once on mount, so anything created
   * during the session (a new note, an undone supersede) never appeared in it. */
  reloadKey?: number;
  className?: string;
}
/** d3 replaces a link's string endpoint with the node object once the simulation runs,
 * so every reader has to handle both shapes. Centralised so the two call sites cannot
 * drift (they were duplicated inline before). */
const endpointId = (e: string | SimNode): string =>
  typeof e === "string" ? e : String(e.id);

const W = 760, H = 620;
const CHARGE = -160, DISTANCE = 70;   // fixed physics (tuning sliders removed)

export default function BrainGraph({ litId, onHover, onPick, onCreateNoteWithTitle, showTags, glowIds, reloadKey = 0, className }: Props) {
  const [data, setData] = useState<BrainGraphDto | null>(null);
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const [links, setLinks] = useState<SimLink[]>([]);
  const reduced = usePrefersReducedMotion();
  const [, tick] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const simRef = useRef<any>(null);

  useEffect(() => { let ok = true; api.getBrainGraph().then((d) => ok && setData(d)).catch(() => ok && setData({ nodes: [], links: [] })); return () => { ok = false; }; }, [reloadKey]);

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
      const s = endpointId(l.source), t = endpointId(l.target);
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

  const radius = (n: SimNode) => {
    if (n.kind === "self") return 16;
    return Math.max(3.5, 3.5 + Math.sqrt(degree.get(n.id) ?? 0) * 2.4);
  };

  const bindDrag = (el: SVGCircleElement | null, node: SimNode) => {
    if (!el) return;
    select(el).call(d3drag<SVGCircleElement, unknown>()
      .on("start", () => { simRef.current?.alphaTarget(0.3).restart(); node.fx = node.x; node.fy = node.y; })
      .on("drag", (e) => { node.fx = e.x; node.fy = e.y; })
      .on("end", () => { simRef.current?.alphaTarget(0); node.fx = null; node.fy = null; }) as any);
  };

  const nbr = litId ? neighbors.get(litId) : null;
  const isLit = (l: SimLink) => {
    const s = endpointId(l.source), t = endpointId(l.target);
    return litId != null && (s === litId || t === litId);
  };
  // 🔴 If the lit id resolves to no node in the CURRENT view, light nothing rather than
  // dimming everything. That happens for real: a persistent tag filter whose tag node is
  // hidden by the 标签 toggle would otherwise black the entire graph out with no way to
  // tell what went wrong.
  const litExists = litId != null && nodes.some((n) => n.id === litId);
  const dimming = litId != null && litExists;

  return (
    <div className={className} style={{ height: "100%", position: "relative" }}>
      <svg ref={svgRef} data-testid="brain-graph" viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "100%", cursor: "grab" }} role="img" aria-label="第二大脑关系图">
        <g ref={gRef}>
          {links.map((l: any, i) => (
            <line key={i} data-link
              x1={l.source?.x ?? 0} y1={l.source?.y ?? 0} x2={l.target?.x ?? 0} y2={l.target?.y ?? 0}
              stroke={dimming && isLit(l) ? "var(--primary)" : "color-mix(in srgb, var(--foreground) 12%, transparent)"}
              strokeOpacity={dimming && !isLit(l) ? 0.25 : 1}
              strokeWidth={dimming && isLit(l) ? 1.6 : 1}
              strokeDasharray={l.type === "provenance" ? "3 3" : undefined} />
          ))}
          {nodes.map((n) => {
            const dim = dimming && litId !== n.id && !(nbr?.has(n.id));
            const r = radius(n);
            const ghost = n.kind === "ghost", self = n.kind === "self", tag = n.kind === "tag";
            const focused = litId === n.id;
            const fill = ghost ? "transparent" : self ? "var(--primary)" : hueVar(tag ? n.label : n.kind);
            return (
              <g key={n.id} style={{ opacity: dim ? 0.2 : 1, transition: reduced ? undefined : "opacity 200ms" }}>
                {(focused || self) && (
                  <circle cx={n.x ?? 0} cy={n.y ?? 0} r={r + 6} fill="none"
                    stroke="var(--primary)" strokeOpacity={0.6} strokeWidth={2}
                    style={{ filter: "drop-shadow(0 0 8px var(--primary))",
                             animation: reduced ? undefined : "brainPulse 1.8s ease-in-out infinite" }} />
                )}
                <circle ref={(el) => bindDrag(el, n)} data-node data-kind={n.kind}
                  cx={n.x ?? 0} cy={n.y ?? 0} r={r} fill={fill}
                  // eslint-disable-next-line -- was literally "white": wrong on a light
                  // theme, and the no-raw-colors guard only catches hex, not keywords.
                  stroke={ghost ? "var(--danger)" : focused || self ? "var(--background)" : "none"}
                  strokeDasharray={ghost ? "2 2" : undefined}
                  strokeWidth={ghost ? 1 : focused || self ? 1.5 : 0}
                  onMouseEnter={(e) => { onHover(n.id); if (!reduced) (e.currentTarget as SVGElement).style.transform = "scale(1.3)"; }}
                  onMouseLeave={(e) => { onHover(null); if (!reduced) (e.currentTarget as SVGElement).style.transform = "scale(1)"; }}
                  onClick={() => { if (!ghost && !self && !tag) onPick({ kind: n.kind as BrainLeaf["kind"], ref: n.ref, label: n.label, provenance: null, confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: n.val }); }}
                  onDoubleClick={() => { if (ghost) onCreateNoteWithTitle(n.label); }}
                  style={{ cursor: ghost || self || tag ? "default" : "pointer", transformOrigin: "center", transformBox: "fill-box", transition: reduced ? undefined : "transform 180ms", filter: glowIds?.has(n.id) ? "drop-shadow(0 0 5px var(--primary))" : undefined }}>
                  {/* native <title> tooltip only — no custom on-hover label; name also
                      shows in the right-rail detail on click. */}
                  <title>{n.label}</title>
                </circle>
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

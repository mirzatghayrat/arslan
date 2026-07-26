import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import { select } from "d3-selection";
import { drag as d3drag } from "d3-drag";
import { zoom as d3zoom } from "d3-zoom";
import { api, type BrainLeaf, type BrainGraphDto, type GraphNodeDto, type GraphLinkDto } from "../../api/client";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { hueVar } from "./hues";
import { hiddenAt, supersedeLinks, type TemporalLink } from "./temporal";

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
  /** F1 — ISO instant, or null for "no filtering at all" (the slider's home). Purely a
   * paint-time filter: it never refetches and never touches what gets injected into a
   * spawn (that path is memory.facts_text -> list_facts, which is active-only and does
   * not read this endpoint). */
  asOf?: string | null;
  /** F1 — reports the fetched nodes up so the as-of slider and the lineage panel can
   * read them. The graph keeps ownership of the fetch (extending, not rebuilding); this
   * only shares the result, so there is still exactly one request per reloadKey. */
  onData?: (nodes: GraphNodeDto[]) => void;
  className?: string;
}
/** d3 replaces a link's string endpoint with the node object once the simulation runs,
 * so every reader has to handle both shapes. Centralised so the two call sites cannot
 * drift (they were duplicated inline before). */
const endpointId = (e: string | SimNode): string =>
  typeof e === "string" ? e : String(e.id);

const W = 760, H = 620;
const CHARGE = -160, DISTANCE = 70;   // fixed physics (tuning sliders removed)

export default function BrainGraph({ litId, onHover, onPick, onCreateNoteWithTitle, showTags, glowIds, reloadKey = 0, asOf = null, onData, className }: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<BrainGraphDto | null>(null);
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const [links, setLinks] = useState<SimLink[]>([]);
  const reduced = usePrefersReducedMotion();
  const [, tick] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const simRef = useRef<any>(null);

  // 🔴 onData is intentionally NOT in the dep array. It is an inline arrow at the call
  // site, so a new identity every render — including it would refetch on every parent
  // render, and the as-of slider (which lives in that parent) re-renders on every drag
  // frame. That would turn a paint-time filter into a request storm.
  const onDataRef = useRef(onData);
  onDataRef.current = onData;
  useEffect(() => {
    let ok = true;
    api.getBrainGraph()
      .then((d) => { if (ok) { setData(d); onDataRef.current?.(d.nodes); } })
      .catch(() => { if (ok) { setData({ nodes: [], links: [] }); onDataRef.current?.([]); } });
    return () => { ok = false; };
  }, [reloadKey]);

  // F1: supersede edges are DERIVED, not sent by the server — superseded_by is a scalar
  // on the node. Merged into `data` (not into `view`) so they take part in the degree
  // map and the simulation exactly like every other edge.
  const withSupersede = useMemo(() => {
    if (!data) return null;
    const extra = supersedeLinks(data.nodes);
    return extra.length === 0 ? data : { ...data, links: [...data.links, ...extra] };
  }, [data]);

  // filtered view: hide tag nodes (+ their edges) when showTags is off
  const view = useMemo(() => {
    if (!withSupersede) return { nodes: [], links: [] };
    if (showTags) return withSupersede;
    const drop = new Set(withSupersede.nodes.filter((n) => n.kind === "tag").map((n) => n.id));
    return {
      nodes: withSupersede.nodes.filter((n) => !drop.has(n.id)),
      links: withSupersede.links.filter((l) => !drop.has(String(l.source)) && !drop.has(String(l.target))),
    };
  }, [withSupersede, showTags]);

  // 🔴 as-of is deliberately NOT part of `view`. Filtering the node array would make
  // forceLink throw on the edges left pointing at removed nodes, and would rebuild the
  // whole simulation on every slider frame — `ns = view.nodes.map(...)` copies from
  // `data`, which d3 never mutated, so every computed x/y would be thrown away and the
  // graph would collapse to the centre and re-anneal as you drag. Instead the arrays
  // stay identical and this only changes how things are painted.
  const hidden = useMemo(
    () => hiddenAt(view.nodes, view.links as TemporalLink[], asOf),
    [view, asOf],
  );

  // degree map (for size) + neighbor map (for hover highlight)
  const { degree, neighbors } = useMemo(() => {
    const deg = new Map<string, number>();
    const nb = new Map<string, Set<string>>();
    view.links.forEach((l) => {
      // radius() is degree-driven, so counting supersede edges would make a REPLACED
      // belief render LARGER than an equivalent live one — working directly against
      // the desaturation that is supposed to mark it as no longer current. They still
      // take part in the simulation and the hover-neighbour set; only size is exempt.
      if (l.type === "supersede") { const s0 = endpointId(l.source), t0 = endpointId(l.target);
        (nb.get(s0) ?? nb.set(s0, new Set()).get(s0)!).add(t0);
        (nb.get(t0) ?? nb.set(t0, new Set()).get(t0)!).add(s0);
        return; }
      const s = endpointId(l.source), t = endpointId(l.target);
      deg.set(s, (deg.get(s) ?? 0) + 1); deg.set(t, (deg.get(t) ?? 0) + 1);
      (nb.get(s) ?? nb.set(s, new Set()).get(s)!).add(t);
      (nb.get(t) ?? nb.set(t, new Set()).get(t)!).add(s);
    });
    return { degree: deg, neighbors: nb };
  }, [view]);

  useEffect(() => {
    if (!withSupersede) return;
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
  }, [view, withSupersede]);   // eslint-disable-line react-hooks/exhaustive-deps

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
        style={{ width: "100%", height: "100%", cursor: "grab" }} role="img" aria-label={t("brain.graph_aria")}>
        <g ref={gRef}>
          {/* arrowhead for supersede edges — the only DIRECTED relation in the graph */}
          <defs>
            <marker id="f1-supersede-arrow" viewBox="0 0 8 8" refX="7" refY="4"
              markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M0,0 L8,4 L0,8 z" fill="var(--hue-9)" />
            </marker>
          </defs>
          {links.map((l: any, i) => {
            const sup = l.type === "supersede";
            // an edge is only as visible as its endpoints: with the node arrays kept
            // whole for d3, a hidden node still has its edges in the array
            const off = hidden.has(endpointId(l.source)) || hidden.has(endpointId(l.target));
            return (
              <line key={i} data-link data-link-type={l.type}
                data-hidden={off ? "true" : undefined}
                x1={l.source?.x ?? 0} y1={l.source?.y ?? 0} x2={l.target?.x ?? 0} y2={l.target?.y ?? 0}
                stroke={sup ? "var(--hue-9)" : dimming && isLit(l) ? "var(--primary)" : "color-mix(in srgb, var(--foreground) 12%, transparent)"}
                strokeOpacity={dimming && !isLit(l) ? 0.25 : 1}
                strokeWidth={dimming && isLit(l) ? 1.6 : 1}
                markerEnd={sup ? "url(#f1-supersede-arrow)" : undefined}
                strokeDasharray={l.type === "provenance" ? "3 3" : undefined}
                style={{ display: off ? "none" : undefined }} />
            );
          })}
          {nodes.map((n) => {
            const dim = dimming && litId !== n.id && !(nbr?.has(n.id));
            const r = radius(n);
            const ghost = n.kind === "ghost", self = n.kind === "self", tag = n.kind === "tag";
            const focused = litId === n.id;
            // F1 — a SEPARATE visual register from ghost, which it must never be
            // confused with. ghost = a [[link]] target that does not exist yet:
            // hollow, dashed, --danger, NOT clickable, double-click creates it.
            // superseded = something that DID exist and was replaced: filled but
            // desaturated, thin solid outline, and clickable — you open it to read
            // the genealogy. Same dashes for both would make "never existed" and
            // "no longer current" look identical while inviting opposite actions.
            const superseded = n.superseded_by != null;
            const off = hidden.has(n.id);
            const fill = ghost ? "transparent" : self ? "var(--primary)" : hueVar(tag ? n.label : n.kind);
            return (
              <g key={n.id} data-node-wrap data-id={n.id}
                data-superseded={superseded ? "true" : undefined}
                data-hidden={off ? "true" : undefined}
                style={{ opacity: dim ? 0.2 : superseded ? 0.45 : 1,
                         display: off ? "none" : undefined,
                         transition: reduced ? undefined : "opacity 200ms" }}>
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
                  stroke={ghost ? "var(--danger)" : focused || self ? "var(--background)" : superseded ? "var(--hue-9)" : "none"}
                  strokeDasharray={ghost ? "2 2" : undefined}   // solid for superseded — dashes stay ghost's alone
                  strokeWidth={ghost ? 1 : focused || self ? 1.5 : superseded ? 1 : 0}
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
        {t("brain.graph_hint")}
      </div>
    </div>
  );
}

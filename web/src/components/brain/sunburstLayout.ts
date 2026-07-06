import type { TreeNode } from "../../hooks/useKnowledgeTree";

const TAU = Math.PI * 2;

export interface Segment {
  id: string; name: string; cat: TreeNode["cat"]; kind: TreeNode["kind"];
  depth: number; a0: number; a1: number; d: string; value: number;
  hueKey?: string; fileType?: string; full?: string;
}
export interface LayoutOpts {
  cx: number; cy: number;
  innerR: number;   // inner hole radius
  outerR: number;   // outer boundary
  bandR: number;    // thin depth-1 top-category band width (root view only)
  padAngle: number; // angular gap between sibling segments (removes hard seams)
  band?: boolean;   // draw the thin depth-1 band (true at true root; false when drilled)
  topMinFrac?: number; // root view only: min angular fraction each top category gets (placeholder for empties)
  gapAngle?: number;   // radians left as a gap at 12 o'clock (root sweep = TAU - gapAngle)
  minReach?: number;   // smallest group's radial reach as a fraction of the span (coxcomb floor)
}

export function arcPath(cx: number, cy: number, ri: number, ro: number, a0: number, a1: number): string {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const p = (r: number, a: number): [number, number] => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const [x0, y0] = p(ro, a0), [x1, y1] = p(ro, a1), [x2, y2] = p(ri, a1), [x3, y3] = p(ri, a0);
  return `M${x0} ${y0}A${ro} ${ro} 0 ${large} 1 ${x1} ${y1}L${x2} ${y2}A${ri} ${ri} 0 ${large} 0 ${x3} ${y3}Z`;
}

/** Deepest branch depth (root=0). */
export function maxDepthOf(tree: TreeNode): number {
  let max = 0;
  const walk = (n: TreeNode, d: number) => {
    max = Math.max(max, d);
    (n.children ?? []).forEach((c) => walk(c, d + 1));
  };
  walk(tree, 0);
  return max;
}

/** Radial ring [ri,ro] for a segment. Root view: depth 1 = thin top-category band;
 * depth>=2 = colored rings filling [bandOuter, reach] over this branch's real depth.
 * Drilled view (no band): colored from depth 1 filling [innerR, reach]. `reach` is the
 * branch's value-scaled outer radius (coxcomb — bigger groups bloom further out), so
 * segments end at different radii instead of one tidy concentric edge. */
function ringForR(depth: number, o: LayoutOpts, reach: number, groupDepth: number,
                  radialStart: number, branchMax: number): [number, number] {
  if (o.band !== false && depth <= 1) return [o.innerR, o.innerR + o.bandR]; // thin top band
  const rings = Math.max(1, branchMax - groupDepth + 1); // groupDepth..branchMax inclusive
  const w = (reach - radialStart) / rings;
  const ri = radialStart + (depth - groupDepth) * w;
  return [ri, ri + w];
}

/** Assign each node (depth>=1) an angular slice ∝ value + an arc at a value-scaled ring.
 * No depth cap. Each branch reaches a different outer radius (coxcomb bloom). */
export function layoutSegments(tree: TreeNode, opts: LayoutOpts): Segment[] {
  const out: Segment[] = [];
  const drilled = opts.band === false;
  const bandOuter = opts.innerR + opts.bandR;
  const groupDepth = drilled ? 1 : 2;                    // the "group" ring level
  const radialStart = drilled ? opts.innerR : bandOuter; // where colored rings begin
  const gap = opts.gapAngle ?? 0;
  const minReach = opts.minReach ?? 0.45;                // smallest groups still reach ~45%

  // Max value among the group-level nodes → scales each branch's radial reach.
  let maxGroupVal = 0;
  const scan = (n: TreeNode, d: number) => {
    if (d === groupDepth) { maxGroupVal = Math.max(maxGroupVal, Math.max(n.value, 0)); return; }
    (n.children ?? []).forEach((c) => scan(c, d + 1));
  };
  scan(tree, 0);
  maxGroupVal = maxGroupVal || 1;

  const place = (node: TreeNode, a0: number, a1: number, depth: number, reach: number, branchMax: number) => {
    if (depth === groupDepth) {
      const frac = Math.pow(Math.max(node.value, 0.0001) / maxGroupVal, 0.6);
      reach = radialStart + (minReach + (1 - minReach) * frac) * (opts.outerR - radialStart);
      branchMax = depth + maxDepthOf(node);              // absolute deepest depth in this branch
    }
    if (depth >= 1) {
      const [ri, ro] = ringForR(depth, opts, reach, groupDepth, radialStart, branchMax);
      out.push({ id: node.id, name: node.name, cat: node.cat, kind: node.kind, depth, a0, a1,
        d: arcPath(opts.cx, opts.cy, ri, ro, a0, a1), value: node.value,
        hueKey: node.hueKey, fileType: node.fileType, full: node.full });
    }
    const kids = node.children ?? [];
    if (kids.length) {
      const pad = opts.padAngle;
      const avail = Math.max(a1 - a0 - pad * kids.length, 0);
      // Root-view top level (depth 0 → depth 1) reserves a floor per category so empty
      // top categories stay visible; deeper levels + drilled views stay pure-proportional.
      const useFloor = depth === 0 && opts.band !== false && (opts.topMinFrac ?? 0) > 0;
      const minF = useFloor ? Math.min(opts.topMinFrac as number, 0.9 / kids.length) : 0;
      // Floor branch: weight children by their *real* value (0 for empties, no epsilon
      // pollution) so the reserved floor is exact; only fall back to an equal split when
      // every child is empty (avoids a 0/0 division).
      const rawSum = kids.reduce((s, c) => s + Math.max(c.value, 0), 0);
      const sumV = kids.reduce((s, c) => s + Math.max(c.value, 0.0001), 0);
      let a = a0 + pad / 2;
      for (const c of kids) {
        const vFrac = useFloor
          ? (rawSum > 0 ? Math.max(c.value, 0) / rawSum : 1 / kids.length)
          : Math.max(c.value, 0.0001) / sumV;
        const frac = useFloor ? (minF + (1 - kids.length * minF) * vFrac) : vFrac;
        const span = frac * avail;
        place(c, a, a + span, depth + 1, reach, branchMax);
        a += span + pad;
      }
    }
  };
  place(tree, -Math.PI / 2 + gap / 2, -Math.PI / 2 + TAU - gap / 2, 0, opts.outerR, maxDepthOf(tree));
  return out;
}

/** node + its ancestors + all descendants, by id. null → empty set. */
export function familyIds(tree: TreeNode, id: string | null): Set<string> {
  const fam = new Set<string>();
  if (!id) return fam;
  const path: TreeNode[] = [];
  const find = (n: TreeNode): boolean => {
    path.push(n);
    if (n.id === id) return true;
    for (const c of n.children ?? []) if (find(c)) return true;
    path.pop();
    return false;
  };
  if (!find(tree)) return fam;
  for (const n of path) fam.add(n.id);
  const target = path[path.length - 1];
  const addDesc = (n: TreeNode) => { fam.add(n.id); (n.children ?? []).forEach(addDesc); };
  addDesc(target);
  return fam;
}

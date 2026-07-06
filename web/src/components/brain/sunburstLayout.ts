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

/** Ring [ri,ro] for a given depth. Root view (band): depth 1 = thin top-category
 * band, depth>=2 = equal-width colored rings over depths 2..maxDepth. Drilled view
 * (no band): depth 1..maxDepth are equal-width colored rings filling the full radius
 * — so drilling into a group whose children are leaves still fills the disk. */
function ringFor(depth: number, maxDepth: number, o: LayoutOpts): [number, number] {
  if (o.band === false) {
    const colorRings = Math.max(1, maxDepth);            // depths 1..maxDepth
    const w = (o.outerR - o.innerR) / colorRings;
    const ri = o.innerR + (depth - 1) * w;
    return [ri, ri + w];
  }
  const bandOuter = o.innerR + o.bandR;
  if (depth <= 1) return [o.innerR, bandOuter];
  const colorRings = Math.max(1, maxDepth - 1);          // depths 2..maxDepth
  const w = (o.outerR - bandOuter) / colorRings;
  const ri = bandOuter + (depth - 2) * w;
  return [ri, ri + w];
}

/** Assign each node (depth>=1) an angular slice ∝ value + an arc at its ring.
 * No depth cap: every branch fans to its own real depth. padAngle removes seams. */
export function layoutSegments(tree: TreeNode, opts: LayoutOpts): Segment[] {
  const out: Segment[] = [];
  const maxDepth = Math.max(1, maxDepthOf(tree));
  const place = (node: TreeNode, a0: number, a1: number, depth: number) => {
    if (depth >= 1) {
      const [ri, ro] = ringFor(depth, maxDepth, opts);
      out.push({ id: node.id, name: node.name, cat: node.cat, kind: node.kind, depth, a0, a1,
        d: arcPath(opts.cx, opts.cy, ri, ro, a0, a1), value: node.value,
        hueKey: node.hueKey, fileType: node.fileType, full: node.full });
    }
    const kids = node.children ?? [];
    if (kids.length) {
      const pad = opts.padAngle;
      const total = kids.reduce((s, c) => s + Math.max(c.value, 0.0001), 0);
      const avail = a1 - a0 - pad * kids.length;
      let a = a0 + pad / 2;
      for (const c of kids) {
        const span = (Math.max(c.value, 0.0001) / total) * Math.max(avail, 0);
        place(c, a, a + span, depth + 1);
        a += span + pad;
      }
    }
  };
  place(tree, -Math.PI / 2, -Math.PI / 2 + TAU, 0);
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

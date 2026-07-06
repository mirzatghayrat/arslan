import type { TreeNode } from "../../hooks/useKnowledgeTree";

const TAU = Math.PI * 2;

export interface Segment {
  id: string; name: string; cat: TreeNode["cat"]; kind: TreeNode["kind"];
  depth: number; a0: number; a1: number; d: string; value: number;
}
export interface LayoutOpts { cx: number; cy: number; rings: (null | [number, number])[]; }

export function arcPath(cx: number, cy: number, ri: number, ro: number, a0: number, a1: number): string {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const p = (r: number, a: number): [number, number] => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const [x0, y0] = p(ro, a0), [x1, y1] = p(ro, a1), [x2, y2] = p(ri, a1), [x3, y3] = p(ri, a0);
  return `M${x0} ${y0}A${ro} ${ro} 0 ${large} 1 ${x1} ${y1}L${x2} ${y2}A${ri} ${ri} 0 ${large} 0 ${x3} ${y3}Z`;
}

/** Assign each node (depth>=1) an angular slice proportional to its value and an
 * arc path at its ring. Returns a flat segment list for rendering. */
export function layoutSegments(tree: TreeNode, opts: LayoutOpts): Segment[] {
  const out: Segment[] = [];
  const rings = opts.rings;
  const place = (node: TreeNode, a0: number, a1: number, depth: number) => {
    if (depth >= 1 && depth <= 3) {
      const rr = rings[depth]!;
      out.push({ id: node.id, name: node.name, cat: node.cat, kind: node.kind, depth, a0, a1,
        d: arcPath(opts.cx, opts.cy, rr[0], rr[1], a0, a1), value: node.value });
    }
    if (node.children && node.children.length) {
      const pad = depth === 0 ? 0.05 : 0.006;
      const total = node.children.reduce((s, c) => s + Math.max(c.value, 0.0001), 0);
      const avail = a1 - a0 - pad * node.children.length;
      let a = a0 + pad / 2;
      for (const c of node.children) {
        const span = (Math.max(c.value, 0.0001) / total) * avail;
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

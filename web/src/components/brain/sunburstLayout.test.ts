import { describe, expect, it } from "vitest";
import { arcPath, familyIds, layoutSegments, maxDepthOf, type LayoutOpts } from "./sunburstLayout";
import type { TreeNode } from "../../hooks/useKnowledgeTree";

const OPTS: LayoutOpts = { cx: 100, cy: 100, innerR: 20, outerR: 100, bandR: 8, padAngle: 0.01 };

const tree: TreeNode = {
  id: "root", name: "YOU", kind: "root", cat: "collection", value: 20,
  children: [
    { id: "cat:collection", name: "共享库", kind: "category", cat: "collection", value: 12, children: [
      { id: "coll:1", name: "A", kind: "collection", cat: "collection", value: 12, children: [
        { id: "src:coll:1:x", name: "x", kind: "source", cat: "collection", value: 12 },
      ] },
    ] },
    { id: "cat:spawn", name: "分身深井", kind: "category", cat: "spawn", value: 8, children: [
      { id: "spawn:1", name: "S", kind: "spawn", cat: "spawn", value: 8, children: [
        { id: "src:spawn:1:y", name: "y", kind: "source", cat: "spawn", value: 8 },
      ] },
    ] },
  ],
};

describe("sunburstLayout", () => {
  it("assigns depth-1 category spans proportional to value, non-overlapping", () => {
    const segs = layoutSegments(tree, OPTS);
    const d1 = segs.filter((s) => s.depth === 1);
    expect(d1.map((s) => s.id).sort()).toEqual(["cat:collection", "cat:spawn"]);
    const coll = d1.find((s) => s.id === "cat:collection")!;
    const spawn = d1.find((s) => s.id === "cat:spawn")!;
    expect(coll.a1 - coll.a0).toBeGreaterThan(spawn.a1 - spawn.a0);
    expect(segs.every((s) => s.a1 > s.a0)).toBe(true);
    expect(segs.some((s) => s.depth === 3 && s.id === "src:coll:1:x")).toBe(true);
    expect(segs.find((s) => s.id === "coll:1")!.d).toMatch(/^M/);
  });

  it("familyIds returns node + ancestors + descendants", () => {
    const fam = familyIds(tree, "coll:1");
    expect(fam.has("coll:1")).toBe(true);
    expect(fam.has("cat:collection")).toBe(true);
    expect(fam.has("src:coll:1:x")).toBe(true);
    expect(fam.has("cat:spawn")).toBe(false);
    expect(familyIds(tree, null).size).toBe(0);
  });

  it("arcPath produces a closed donut-segment path", () => {
    const d = arcPath(100, 100, 30, 55, 0, Math.PI / 2);
    expect(d.startsWith("M")).toBe(true);
    expect(d.trim().endsWith("Z")).toBe(true);
  });
});

const deepTree: any = { id: "root", name: "YOU", kind: "root", cat: "collection", value: 3, children: [
  { id: "cat:spawn", name: "分身", kind: "category", cat: "spawn", value: 3, children: [
    { id: "dom:research", name: "research", kind: "category", cat: "spawn", value: 3, hueKey: "research", children: [
      { id: "spawn:1", name: "R", kind: "spawn", cat: "spawn", value: 3, hueKey: "R", children: [
        { id: "src:1", name: "a.pdf", kind: "source", cat: "spawn", value: 3, fileType: "pdf" }]}]}]}]};

it("maxDepthOf returns the deepest branch depth", () => {
  expect(maxDepthOf(deepTree)).toBe(4);
});

it("lays out every node beyond depth 3 (no 3-ring cap)", () => {
  const segs = layoutSegments(deepTree, OPTS);
  const ids = segs.map((s) => s.id);
  expect(ids).toContain("spawn:1");
  expect(ids).toContain("src:1");
  const src = segs.find((s) => s.id === "src:1")!;
  expect(src.depth).toBe(4);
});

it("reserves a min angle for empty top categories + a top gap (root view)", () => {
  const opts = { cx: 0, cy: 0, innerR: 20, outerR: 100, bandR: 8, padAngle: 0, topMinFrac: 0.1, gapAngle: 0.2 } as any;
  const t: any = { id: "root", name: "YOU", kind: "root", cat: "collection", value: 10, children: [
    { id: "cat:collection", name: "库", kind: "category", cat: "collection", value: 0, children: [] },
    { id: "cat:spawn", name: "分身", kind: "category", cat: "spawn", value: 0, children: [] },
    { id: "cat:pref", name: "偏好", kind: "category", cat: "pref", value: 10, children: [
      { id: "pref:1", name: "a", kind: "pref", cat: "pref", value: 10 }] },
  ]};
  const segs = layoutSegments(t, opts);
  const ang = (id: string) => { const s = segs.find((x) => x.id === id)!; return s.a1 - s.a0; };
  const TAU = Math.PI * 2;
  const top = ["cat:collection", "cat:spawn", "cat:pref"].map(ang);
  expect(top.reduce((a, b) => a + b, 0)).toBeCloseTo(TAU - 0.2, 5);
  expect(ang("cat:collection")).toBeCloseTo(0.1 * (TAU - 0.2), 5);
  expect(ang("cat:spawn")).toBeCloseTo(0.1 * (TAU - 0.2), 5);
  expect(ang("cat:pref")).toBeGreaterThan(0.5 * (TAU - 0.2));
});

it("does NOT apply the floor when drilled (band=false)", () => {
  const opts = { cx: 0, cy: 0, innerR: 20, outerR: 100, bandR: 8, padAngle: 0, topMinFrac: 0.1, gapAngle: 0, band: false } as any;
  const t: any = { id: "g", name: "任务", kind: "category", cat: "pref", value: 4, children: [
    { id: "a", name: "a", kind: "pref", cat: "pref", value: 3 },
    { id: "b", name: "b", kind: "pref", cat: "pref", value: 1 },
  ]};
  const segs = layoutSegments(t, opts);
  const ang = (id: string) => { const s = segs.find((x) => x.id === id)!; return s.a1 - s.a0; };
  expect(ang("a") / ang("b")).toBeCloseTo(3, 4);
});

import { describe, expect, it } from "vitest";
import { arcPath, familyIds, layoutSegments } from "./sunburstLayout";
import type { TreeNode } from "../../hooks/useKnowledgeTree";

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
    const segs = layoutSegments(tree, { cx: 100, cy: 100, rings: [null, [30, 55], [58, 78], [81, 98]] });
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

import { useCallback, useEffect, useState } from "react";
import { api, type BrainBranch } from "../api/client";
import type { TreeNode } from "./useKnowledgeTree";

/** Adapt the typed /brain/tree (three branches, each leaf carrying value = 1+usage)
 * into the TreeNode shape the sunburst already understands. Angular size comes from
 * `value` (usage-weighted, never zero); color comes from `hueKey` = the type kind
 * (material/learning/profile), which hueVar() maps to a fixed per-type hue. */
export function brainBranchesToTree(branches: BrainBranch[]): TreeNode {
  const cats = branches.map((b): TreeNode => {
    const leaves = b.children.map((l): TreeNode => ({
      id: l.ref, name: l.label, kind: "source", cat: "collection",
      value: l.value, hueKey: b.kind, full: l.provenance ?? l.label,
    }));
    const bval = leaves.reduce((s, l) => s + l.value, 0);
    return {
      id: `cat:${b.kind}`, name: b.label, kind: "category", cat: "collection",
      value: bval, hueKey: b.kind, children: leaves,
    };
  });
  const root: TreeNode = {
    id: "root", name: "YOU", kind: "root", cat: "collection",
    value: cats.reduce((s, c) => s + c.value, 0), children: cats,
  };
  return root;
}

/** Refs of leaves used within the last 24h — the sunburst glows these. */
export function recentIds(branches: BrainBranch[]): Set<string> {
  const now = Date.now();
  const ids = new Set<string>();
  for (const b of branches) {
    for (const l of b.children) {
      if (!l.last_used_at) continue;
      const t = Date.parse(l.last_used_at);
      if (!Number.isNaN(t) && now - t < 24 * 3600 * 1000) ids.add(l.ref);
    }
  }
  return ids;
}

export function useBrainTree() {
  const [branches, setBranches] = useState<BrainBranch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setBranches((await api.getBrainTree()).branches); }
    catch (e) { setError(e instanceof Error ? e.message : "failed to load brain"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  return { branches, loading, error, refresh: load };
}

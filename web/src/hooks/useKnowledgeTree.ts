import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

export type NodeKind = "root" | "category" | "collection" | "spawn" | "source" | "pref";
export type Cat = "collection" | "spawn" | "pref";

export interface TreeNode {
  id: string;
  name: string;
  kind: NodeKind;
  cat: Cat;
  value: number;
  children?: TreeNode[];
}

function sum(n: TreeNode): number {
  if (!n.children || n.children.length === 0) return n.value;
  n.value = n.children.reduce((s, c) => s + sum(c), 0);
  return n.value;
}

/** Assemble the whole second-brain as one hierarchical tree — the single data
 * source for both the left nav and the right sunburst. Existing objects only,
 * no backend changes. Every fetch degrades to [] so a failure yields a
 * root-only skeleton, never a crash. */
export function useKnowledgeTree() {
  const [tree, setTree] = useState<TreeNode>({ id: "root", name: "YOU", kind: "root", cat: "collection", value: 0, children: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [spawns, facts, collections] = await Promise.all([
        api.listSpawns().catch(() => []),
        api.listFacts().catch(() => []),
        api.listCollections().catch(() => []),
      ]);
      const [spawnKbs, collKbs] = await Promise.all([
        Promise.all(spawns.map((s) => api.getKnowledge(s.id).catch(() => []))),
        Promise.all(collections.map((c) => api.getCollectionKnowledge(c.id).catch(() => []))),
      ]);

      const collChildren: TreeNode[] = collections.map((c, i): TreeNode => ({
        id: `coll:${c.id}`, name: c.name, kind: "collection", cat: "collection", value: 0,
        children: collKbs[i].map((s): TreeNode => ({
          id: `src:coll:${c.id}:${s.source}`, name: s.source, kind: "source", cat: "collection", value: s.chunks,
        })),
      }));
      const spawnChildren: TreeNode[] = spawns.map((s, i): TreeNode => ({
        id: `spawn:${s.id}`, name: s.name, kind: "spawn", cat: "spawn", value: 0,
        children: spawnKbs[i].map((k): TreeNode => ({
          id: `src:spawn:${s.id}:${k.source}`, name: k.source, kind: "source", cat: "spawn", value: k.chunks,
        })),
      }));
      const prefChildren: TreeNode[] = facts.map((f): TreeNode => ({
        id: `pref:${f.id}`, name: f.content, kind: "pref", cat: "pref", value: 1,
      }));

      const root: TreeNode = {
        id: "root", name: "YOU", kind: "root", cat: "collection", value: 0,
        children: [
          { id: "cat:collection", name: "共享库", kind: "category", cat: "collection", value: 0, children: collChildren },
          { id: "cat:spawn", name: "分身深井", kind: "category", cat: "spawn", value: 0, children: spawnChildren },
          { id: "cat:pref", name: "偏好", kind: "category", cat: "pref", value: 0, children: prefChildren },
        ],
      };
      sum(root);
      setTree(root);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load knowledge tree");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  return { tree, loading, error, refresh: load };
}

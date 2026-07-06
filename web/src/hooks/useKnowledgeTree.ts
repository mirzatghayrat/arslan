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
  /** Set on source leaves: coarse file-type bucket derived from the source name. */
  fileType?: string;
  /** Grouping key used to drive sunburst/nav color (category name, domain, collection, etc). */
  hueKey?: string;
  /** Full content for pref leaves, kept for hover tooltips when name is a short label. */
  full?: string;
}

function sum(n: TreeNode): number {
  if (!n.children || n.children.length === 0) return n.value;
  n.value = n.children.reduce((s, c) => s + sum(c), 0);
  return n.value;
}

/** Coarse file-type bucket for a source name/URL, used to color source leaves. */
export function fileTypeOf(name: string): string {
  const n = name.toLowerCase();
  if (/^https?:\/\//.test(n)) return "url";
  if (/\.(pdf)$/.test(n)) return "pdf";
  if (/\.(docx?|rtf)$/.test(n)) return "doc";
  if (/\.(txt|md|markdown)$/.test(n)) return "text";
  if (/\.(png|jpe?g|gif|webp|bmp)$/.test(n)) return "image";
  return "other";
}

/** Group items into stable-order buckets keyed by a derived key, falling back
 * to "其他" when the key is missing/empty. Preserves first-appearance order. */
function groupBy<T>(items: T[], keyOf: (item: T) => string | null | undefined): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const raw = keyOf(item);
    const key = raw && raw.trim() ? raw : "其他";
    const list = groups.get(key);
    if (list) list.push(item);
    else groups.set(key, [item]);
  }
  return groups;
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
        id: `coll:${c.id}`, name: c.name, kind: "collection", cat: "collection", value: 0, hueKey: c.name,
        children: collKbs[i].map((s): TreeNode => ({
          id: `src:coll:${c.id}:${s.source}`, name: s.source, kind: "source", cat: "collection", value: s.chunks,
          fileType: fileTypeOf(s.source), hueKey: `ft:${fileTypeOf(s.source)}`,
        })),
      }));

      // Spawns: group top-level by domain (first segment before "."), fallback "其他".
      const spawnDomainGroups = groupBy(
        spawns.map((s, i) => ({ s, i })),
        ({ s }) => s.domain?.split(".")[0],
      );
      const spawnChildren: TreeNode[] = Array.from(spawnDomainGroups.entries()).map(([domain, entries]): TreeNode => ({
        id: `dom:${domain}`, name: domain, kind: "category", cat: "spawn", value: 0, hueKey: domain,
        children: entries.map(({ s, i }): TreeNode => ({
          id: `spawn:${s.id}`, name: s.name, kind: "spawn", cat: "spawn", value: 0, hueKey: s.name,
          children: spawnKbs[i].map((k): TreeNode => ({
            id: `src:spawn:${s.id}:${k.source}`, name: k.source, kind: "source", cat: "spawn", value: k.chunks,
            fileType: fileTypeOf(k.source), hueKey: `ft:${fileTypeOf(k.source)}`,
          })),
        })),
      }));

      // Prefs: group top-level by category label, fallback "其他".
      const prefCategoryGroups = groupBy(facts, (f) => f.category);
      const prefChildren: TreeNode[] = Array.from(prefCategoryGroups.entries()).map(([category, groupFacts]): TreeNode => ({
        id: `pref-grp:${category}`, name: category, kind: "category", cat: "pref", value: 0, hueKey: category,
        children: groupFacts.map((f): TreeNode => ({
          id: `pref:${f.id}`, name: f.label || f.content, kind: "pref", cat: "pref", value: 1,
          // inherit the category hue so ring2 (group) + ring3 (its prefs) form one
          // coherent concentric color wedge instead of a two-tone split.
          hueKey: category, full: f.content,
        })),
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

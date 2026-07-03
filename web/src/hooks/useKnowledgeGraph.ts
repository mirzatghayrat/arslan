import { useCallback, useEffect, useState } from "react";
import type { OrreryNodeIn, OrreryEdgeIn } from "../components/orrery/orreryLayout";
import { api } from "../api/client";

export interface KnowledgeGraph {
  nodes: OrreryNodeIn[];
  edges: OrreryEdgeIn[];
}

/**
 * Fetches the user's real data (spawns, their knowledge sources, and user
 * facts) and assembles it into `{ nodes, edges }` for the KnowledgeOrrery.
 * No dedicated backend endpoint — composed from existing API methods.
 *
 * - Hub node "YOU" is always present.
 * - Each spawn becomes a node linked to the hub.
 * - Each knowledge source becomes a node; sources sharing a name across
 *   spawns are deduped into a single node, with an edge from every spawn
 *   that uses it.
 * - Each user fact becomes a preference node linked to the hub.
 * - On empty data or failure the graph is hub-only.
 */
export function useKnowledgeGraph() {
  const [graph, setGraph] = useState<KnowledgeGraph>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const spawns = await api.listSpawns();
      const facts = await api.listFacts().catch(() => []);
      // fetch each spawn's knowledge sources in parallel
      const kbs = await Promise.all(
        spawns.map((s) => api.getKnowledge(s.id).catch(() => [])),
      );

      const nodes: OrreryNodeIn[] = [{ id: "hub", cat: "hub", label: "YOU" }];
      const edges: OrreryEdgeIn[] = [];
      const sourceId = (name: string) => `src:${name}`;
      const seenSource = new Set<string>();

      spawns.forEach((s, i) => {
        const sid = `spawn:${s.id}`;
        nodes.push({
          id: sid,
          cat: "spawn",
          label: s.name,
          meta: s.domain ?? "spawn",
          imp: 0.9,
        });
        edges.push({ a: "hub", b: sid });
        for (const src of kbs[i]) {
          const nid = sourceId(src.source);
          if (!seenSource.has(nid)) {
            // dedup cross-spawn same-named source into one node
            seenSource.add(nid);
            nodes.push({
              id: nid,
              cat: "source",
              label: src.source,
              meta: `${src.chunks} chunks`,
            });
          }
          edges.push({ a: sid, b: nid }); // this spawn uses this source
        }
      });

      facts.forEach((f, i) => {
        const fid = `pref:${f.id ?? i}`;
        nodes.push({ id: fid, cat: "pref", label: f.content, meta: "preference" });
        edges.push({ a: "hub", b: fid });
      });

      setGraph({ nodes, edges });
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load knowledge graph");
      // hub-only on failure
      setGraph({ nodes: [{ id: "hub", cat: "hub", label: "YOU" }], edges: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { graph, loading, error, refresh: load };
}

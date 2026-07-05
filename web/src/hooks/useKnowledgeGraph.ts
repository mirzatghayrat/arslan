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
 * - Each shared collection becomes a "collection" node linked to the hub,
 *   with edges to bound spawns and to its sources (sources share the same
 *   `src:` namespace/dedup as spawn sources).
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
      // the three top-level fetches are independent — fire them together
      // instead of serializing (listSpawns keeps its current, uncaught
      // error behavior; the other two keep their existing .catch fallback)
      const [spawns, facts, collections] = await Promise.all([
        api.listSpawns(),
        api.listFacts().catch(() => []),
        api.listCollections().catch(() => []),
      ]);
      // fetch each spawn's / collection's knowledge sources in parallel
      // (these genuinely depend on the id lists above)
      const [kbs, collKbs] = await Promise.all([
        Promise.all(spawns.map((s) => api.getKnowledge(s.id).catch(() => []))),
        Promise.all(collections.map((c) => api.getCollectionKnowledge(c.id).catch(() => []))),
      ]);

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

      collections.forEach((c, i) => {
        const cid = `coll:${c.id}`;
        nodes.push({ id: cid, cat: "collection", label: c.name, meta: `${c.chunks} chunks`, imp: 0.8 });
        edges.push({ a: "hub", b: cid });
        for (const sid of c.spawn_ids) {
          if (spawns.some((s) => s.id === sid)) edges.push({ a: `spawn:${sid}`, b: cid });
        }
        for (const src of collKbs[i]) {
          const nid = sourceId(src.source);
          if (!seenSource.has(nid)) {
            // dedup against spawn sources — same `src:` namespace
            seenSource.add(nid);
            nodes.push({
              id: nid,
              cat: "source",
              label: src.source,
              meta: `${src.chunks} chunks`,
            });
          }
          edges.push({ a: cid, b: nid }); // this collection contains this source
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

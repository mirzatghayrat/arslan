import { useCallback, useEffect, useState } from "react";
import { api, type BrainBranch } from "../api/client";

/** Refs of leaves used within the last 24h — the graph glows these. */
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

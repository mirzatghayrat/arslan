import { create } from "zustand";
import { api } from "../api/client";

/**
 * Real capability display-name map, loaded once from the backend registry
 * (GET /registry). Keys are toolset keys and skill keys — the same keys carried
 * by a spawn's equipment / `tools` / `skills` arrays. Chips resolve a key to its
 * REAL name via this map; when a key is absent the raw key is rendered instead.
 *
 * Honesty rule: this map NEVER contains invented capability names. If the backend
 * is unreachable it stays empty and chips fall back to the raw key — never to
 * fabricated data.
 */
interface RegistryNamesState {
  names: Record<string, string>;
  loaded: boolean;
  loading: boolean;
  loadRegistry: () => Promise<void>;
}

export const useRegistryStore = create<RegistryNamesState>((set, get) => ({
  names: {},
  loaded: false,
  loading: false,
  loadRegistry: async () => {
    const { loaded, loading } = get();
    if (loaded || loading) return;
    set({ loading: true });
    try {
      const cat = await api.getRegistry();
      const names: Record<string, string> = {};
      for (const ts of cat.toolsets) {
        if (ts.key && ts.name) names[ts.key] = ts.name;
      }
      for (const sk of cat.skills) {
        if (sk.key && sk.name) names[sk.key] = sk.name;
      }
      set({ names, loaded: true, loading: false });
    } catch {
      // Leave names empty and loaded=false so a later mount can retry; never
      // substitute fabricated names.
      set({ loading: false });
    }
  },
}));

/**
 * Hook returning a resolver: capability key → real display name, or the raw key
 * when unknown. Use for every equipped-capability chip.
 */
export function useCapabilityLabel(): (key: string) => string {
  const names = useRegistryStore((s) => s.names);
  return (key: string) => names[key] ?? key;
}

import { create } from "zustand";
import { api } from "../api/client";
import type { SpawnSummary } from "../types";

interface SpawnState {
  spawns: SpawnSummary[];
  loading: boolean;
  error: string;
  load: () => Promise<void>;
  remove: (id: number) => Promise<void>;
}

export const useSpawnStore = create<SpawnState>((set, get) => ({
  spawns: [],
  loading: false,
  error: "",
  load: async () => {
    set({ loading: true, error: "" });
    try {
      const spawns = await api.listSpawns();
      set({ spawns, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },
  remove: async (id) => {
    await api.deleteSpawn(id);
    set({ spawns: get().spawns.filter((s) => s.id !== id) });
  },
}));

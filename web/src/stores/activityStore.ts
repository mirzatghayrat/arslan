import { create } from "zustand";

export type UsageRange = "24h" | "7d" | "30d";

/** What 最近的工作 is narrowed to: a slice of the chart (epoch seconds) and/or one model. */
export interface ActivityFilter {
  since?: number;
  until?: number;
  model?: string;
}

/**
 * Activity's place (0.1.58 §7): the range, the filter, the run open in the drawer and
 * where each box was scrolled. The page unmounts when you leave it (App mounts only the
 * active section), so this lives outside it — coming back lands where you were. Memory
 * only: an app restart starts fresh.
 */
interface ActivityState {
  range: UsageRange;
  filter: ActivityFilter;
  openRunId: number | null;
  scroll: Record<string, number>;
  setRange: (range: UsageRange) => void;
  setFilter: (filter: ActivityFilter) => void;
  setOpenRun: (id: number | null) => void;
  saveScroll: (key: string, top: number) => void;
}

export const useActivityStore = create<ActivityState>((set) => ({
  range: "7d",
  filter: {},
  openRunId: null,
  scroll: {},
  setRange: (range) => set({ range }),
  setFilter: (filter) => set((s) => ({ filter, scroll: { ...s.scroll, runs: 0 } })),
  setOpenRun: (openRunId) => set({ openRunId }),
  saveScroll: (key, top) => set((s) => (s.scroll[key] === top ? s : { scroll: { ...s.scroll, [key]: top } })),
}));

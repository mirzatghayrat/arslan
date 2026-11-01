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
 * only: an app restart starts fresh. Since v0.1.64 (INB7-a) the page is called Progress;
 * it also keeps whether the cost by model is open, and which chart colour each model has.
 */
interface ActivityState {
  range: UsageRange;
  filter: ActivityFilter;
  openRunId: number | null;
  /** INB7-b: the run picked on the time axis, whose steps it shows and replays. Apart from openRunId (the drawer) until INB7-c's
   *  inspector takes the drawer's place and one pick drives both. */
  axisRunId: number | null;
  scroll: Record<string, number>;
  byModelOpen: boolean;
  /** model → its slot in the chart palette (0–2), so a model keeps its colour when the range changes. */
  modelSlots: Record<string, number>;
  setRange: (range: UsageRange) => void;
  setFilter: (filter: ActivityFilter) => void;
  setOpenRun: (id: number | null) => void;
  setAxisRun: (id: number | null) => void;
  saveScroll: (key: string, top: number) => void;
  setByModelOpen: (open: boolean) => void;
  rememberSlots: (slots: Record<string, number>) => void;
}

export const useActivityStore = create<ActivityState>((set) => ({
  range: "7d",
  filter: {},
  openRunId: null,
  axisRunId: null,
  scroll: {},
  byModelOpen: false,
  modelSlots: {},
  setRange: (range) => set({ range }),
  setFilter: (filter) => set((s) => ({ filter, scroll: { ...s.scroll, runs: 0 } })),
  setOpenRun: (openRunId) => set({ openRunId }),
  setAxisRun: (axisRunId) => set({ axisRunId }),
  saveScroll: (key, top) => set((s) => (s.scroll[key] === top ? s : { scroll: { ...s.scroll, [key]: top } })),
  setByModelOpen: (byModelOpen) => set({ byModelOpen }),
  rememberSlots: (slots) => set((s) => (Object.entries(slots).every(([model, slot]) => s.modelSlots[model] === slot) ? s
    : { modelSlots: { ...s.modelSlots, ...slots } })),
}));

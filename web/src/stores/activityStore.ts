import { create } from "zustand";
import type { RunListItem } from "../api/client.types";

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
  /** INB7-c1: the page's one pick. A bar on the axis or a row of 「最近的工作」 picks a run; the axis shows its steps and the
   *  inspector opens it. The drawer (openRunId) is one click away from the inspector until INB7-c4. */
  pickedRunId: number | null;
  /** The picked run as it was listed when picked, for the inspector's header when the list it came from is not the one loaded. */
  pickedRun: RunListItem | null;
  /** The replay of the picked run, shared by the axis's step lane (which plays it) and the inspector's step list: the step shown
   *  last (null: all of them) and whether it is playing. Picking another run starts it over. */
  replayStep: number | null;
  replayPlaying: boolean;
  scroll: Record<string, number>;
  byModelOpen: boolean;
  /** model → its slot in the chart palette (0–2), so a model keeps its colour when the range changes. */
  modelSlots: Record<string, number>;
  setRange: (range: UsageRange) => void;
  setFilter: (filter: ActivityFilter) => void;
  setOpenRun: (id: number | null) => void;
  setPickedRun: (id: number | null, run?: RunListItem | null) => void;
  /** Opens a run in the drawer and picks it, so the list, the axis and the inspector follow (a reply's link, the drawer's arrows). */
  showRun: (id: number, run?: RunListItem | null) => void;
  setReplay: (replay: { step?: number | null; playing?: boolean }) => void;
  saveScroll: (key: string, top: number) => void;
  setByModelOpen: (open: boolean) => void;
  rememberSlots: (slots: Record<string, number>) => void;
}

export const useActivityStore = create<ActivityState>((set) => ({
  range: "7d",
  filter: {},
  openRunId: null,
  pickedRunId: null,
  pickedRun: null,
  replayStep: null,
  replayPlaying: false,
  scroll: {},
  byModelOpen: false,
  modelSlots: {},
  // A new range has a new axis: its replay starts over (⓪Plan's review of PR 624, C).
  setRange: (range) => set({ range, replayStep: null, replayPlaying: false }),
  setFilter: (filter) => set((s) => ({ filter, scroll: { ...s.scroll, runs: 0 } })),
  setOpenRun: (openRunId) => set({ openRunId }),
  setPickedRun: (pickedRunId, run = null) => set({ pickedRunId, pickedRun: pickedRunId == null ? null : run, replayStep: null,
    replayPlaying: false }),
  showRun: (id, run = null) => set({ openRunId: id, pickedRunId: id, pickedRun: run, replayStep: null, replayPlaying: false }),
  setReplay: ({ step, playing }) => set((s) => ({ replayStep: step === undefined ? s.replayStep : step,
    replayPlaying: playing ?? s.replayPlaying })),
  saveScroll: (key, top) => set((s) => (s.scroll[key] === top ? s : { scroll: { ...s.scroll, [key]: top } })),
  setByModelOpen: (byModelOpen) => set({ byModelOpen }),
  rememberSlots: (slots) => set((s) => (Object.entries(slots).every(([model, slot]) => s.modelSlots[model] === slot) ? s
    : { modelSlots: { ...s.modelSlots, ...slots } })),
}));

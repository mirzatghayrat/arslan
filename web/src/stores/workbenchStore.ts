import { create } from "zustand";
import type { StoredArtifact } from "../api/client.types";

export type WorkbenchTab = "task" | "files" | "browser";
/** What the reader shows: a file Arslan delivered (its snapshot), or a file on disk by path. */
export type ReaderSource = { kind: "artifact"; file: StoredArtifact } | { kind: "path"; path: string };

const WIDTH_KEY = "arslan.workbench.width.v1";
export const MIN_WIDTH = 320;
export const MAX_WIDTH = 760;
export const READER_WIDTH = 560;

function savedWidth(): number {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY));
    return Number.isFinite(n) && n >= MIN_WIDTH && n <= MAX_WIDTH ? n : 380;
  } catch { return 380; }
}

/**
 * The right-hand workbench (0.1.58 §3): one panel with 任务 / 文件 / 浏览器 and a reader that
 * slides over them. It never opens by itself (0.1.42 rule) — only a click opens it: the title
 * bar toggle, a file card, a path in a reply, "后台 N".
 */
interface WorkbenchState {
  open: boolean;
  tab: WorkbenchTab;
  reader: ReaderSource | null;
  /** The 文件 tab's folder (null = the conversation's own folder). */
  folder: string | null;
  width: number;
  show: (tab?: WorkbenchTab) => void;
  toggle: () => void;
  close: () => void;
  openReader: (source: ReaderSource) => void;
  closeReader: () => void;
  browse: (folder: string | null) => void;
  setWidth: (w: number) => void;
}

export const useWorkbench = create<WorkbenchState>((set, get) => ({
  open: false,
  tab: "task",
  reader: null,
  folder: null,
  width: savedWidth(),
  show: (tab) => set({ open: true, ...(tab ? { tab, reader: null } : {}) }),
  toggle: () => set({ open: !get().open }),
  close: () => set({ open: false }),
  openReader: (reader) => set({ open: true, reader }),
  closeReader: () => set({ reader: null }),
  browse: (folder) => set({ open: true, tab: "files", folder, reader: null }),
  setWidth: (w) => {
    const width = Math.round(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w)));
    try { localStorage.setItem(WIDTH_KEY, String(width)); } catch { /* storage off */ }
    set({ width });
  },
}));

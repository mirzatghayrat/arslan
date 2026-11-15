import { create } from "zustand";
import type { StoredArtifact } from "../api/client.types";
import { sideChatsApi, type SideChat } from "../api/sideChats";

/** WB1 (v0.1.64): a fixed row, Overview (WB1-2, the default), Working folder (id "files"), Progress and Browser. */
export type FixedTab = "overview" | "files" | "progress" | "browser";
/** SIDE-2: a side chat's tab is its conversation id (`side-…`, SIDE-1's prefix). */
export type SideTab = `side-${string}`;
export type WorkbenchTab = FixedTab | SideTab;
export const isSideTab = (tab: WorkbenchTab): tab is SideTab => tab.startsWith("side-");
/** What the reader shows: a file Arslan delivered (its snapshot), a file on disk by path, (DIFF1) one path a
 * turn changed, as a side-by-side line diff opened from Overview's Changes, or (L11-0) a folder-rules file's text. */
export type ReaderSource = { kind: "artifact"; file: StoredArtifact } | { kind: "path"; path: string }
  | { kind: "diff"; conversationId: string; runId: number; folder: string; path: string }
  | { kind: "repo-diff"; conversationId: string; folder: string; path: string }
  /** L11-0: a folder-rules file Overview already holds the text of (it may sit above the readable folders). */
  | { kind: "text"; name: string; text: string };

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
 * The right-hand workbench (0.1.58 §3, WB1): one panel with Overview / Working folder / Progress / Browser and
 * a reader that slides over them. It never opens by itself (0.1.42 rule) — only a click opens it:
 * the title bar toggle, a file card, a path in a reply, "后台 N".
 */
interface WorkbenchState {
  open: boolean;
  tab: WorkbenchTab;
  reader: ReaderSource | null;
  /** The Working folder tab's folder (null = the conversation's own folder). */
  folder: string | null;
  width: number;
  show: (tab?: WorkbenchTab) => void;
  toggle: () => void;
  close: () => void;
  openReader: (source: ReaderSource) => void;
  closeReader: () => void;
  /** DIFF2: an address for the Browser tab to open in a new browser tab (a PR's link), taken once by WorkDock. */
  pendingUrl: string | null;
  openUrl: (url: string) => void;
  takeUrl: () => string | null;
  browse: (folder: string | null) => void;
  setWidth: (w: number) => void;
  /** SIDE-2: the panel at its widest (the side chat's expand). */
  expanded: boolean;
  toggleExpanded: () => void;
  /** SIDE-2: each conversation's side chats (GET, oldest first), which of them have a tab, and the quote waiting in
   * a side chat's input (never sent until the user sends). Open or closed is the window's to remember (SIDE-1). */
  sides: Record<string, SideChat[]>;
  openSides: Record<string, SideTab[]>;
  sideQuotes: Record<string, string>;
  loadSides: (parentId: string) => Promise<void>;
  /** POST a side chat, branched at `branchMessageId` (none: the newest message, "+"), and select its new tab. */
  startSide: (parentId: string, branchMessageId?: number | null, quote?: string) => Promise<SideTab>;
  openSide: (parentId: string, id: SideTab) => void;
  /** Only the tab closes: the side chat stays and comes back from Overview's list (the user, 2026-11-11). */
  closeSide: (parentId: string, id: SideTab) => void;
  deleteSide: (parentId: string, id: SideTab) => Promise<void>;
  setSideQuote: (id: SideTab, quote: string | null) => void;
}

/** WB1 rule 7: a selected side chat that goes falls back to Overview, and the panel stays open. */
const FALLBACK: FixedTab = "overview";
/** Side chats deleted from this window (ids are never reused: `side-` and a UUID). */
const deletedSides = new Set<string>();

export const useWorkbench = create<WorkbenchState>((set, get) => ({
  open: false,
  tab: "overview",
  reader: null,
  folder: null,
  width: savedWidth(),
  show: (tab) => set({ open: true, ...(tab ? { tab, reader: null } : {}) }),
  toggle: () => set({ open: !get().open }),
  close: () => set({ open: false }),
  openReader: (reader) => set({ open: true, reader }),
  closeReader: () => set({ reader: null }),
  pendingUrl: null,
  openUrl: (url) => set({ open: true, tab: "browser", reader: null, pendingUrl: url }),
  takeUrl: () => { const url = get().pendingUrl; if (url) set({ pendingUrl: null }); return url; },
  browse: (folder) => set({ open: true, tab: "files", folder, reader: null }),
  setWidth: (w) => {
    const width = Math.round(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w)));
    try { localStorage.setItem(WIDTH_KEY, String(width)); } catch { /* storage off */ }
    set({ width });
  },
  expanded: false,
  toggleExpanded: () => set({ expanded: !get().expanded }),
  sides: {},
  openSides: {},
  sideQuotes: {},
  loadSides: async (parentId) => {
    const asked = new Set((get().sides[parentId] ?? []).map((c) => c.conversation_id));
    const list = await sideChatsApi.list(parentId);
    // One started while the list was on its way is kept, after the server's (it is the newest).
    const since = (get().sides[parentId] ?? []).filter((c) => !asked.has(c.conversation_id)
      && !list.some((x) => x.conversation_id === c.conversation_id));
    // A list asked for before a delete went through still names the deleted one: it stays gone.
    const kept = list.filter((c) => !deletedSides.has(c.conversation_id));
    set({ sides: { ...get().sides, [parentId]: [...kept, ...since] } });
  },
  startSide: async (parentId, branchMessageId, quote) => {
    const made = await sideChatsApi.create(parentId, branchMessageId ?? null);
    const id = made.conversation_id as SideTab;
    const list = (get().sides[parentId] ?? []).filter((c) => c.conversation_id !== id);
    set({ sides: { ...get().sides, [parentId]: [...list, made] } });
    if (quote?.trim()) get().setSideQuote(id, quote);
    get().openSide(parentId, id);
    return id;
  },
  openSide: (parentId, id) => {
    const open = get().openSides[parentId] ?? [];
    set({ open: true, tab: id, reader: null,
      openSides: { ...get().openSides, [parentId]: open.includes(id) ? open : [...open, id] } });
  },
  closeSide: (parentId, id) => {
    const open = (get().openSides[parentId] ?? []).filter((x) => x !== id);
    set({ openSides: { ...get().openSides, [parentId]: open }, ...(get().tab === id ? { tab: FALLBACK } : {}) });
  },
  deleteSide: async (parentId, id) => {
    // Marked before the request, so a list landing while it is on its way can't bring it back; unmarked if it fails.
    deletedSides.add(id);
    try { await sideChatsApi.remove(id); } catch (err) { deletedSides.delete(id); throw err; }
    get().closeSide(parentId, id);
    get().setSideQuote(id, null);
    set({ sides: { ...get().sides, [parentId]: (get().sides[parentId] ?? []).filter((c) => c.conversation_id !== id) } });
  },
  setSideQuote: (id, quote) => {
    const { [id]: _gone, ...rest } = get().sideQuotes;
    set({ sideQuotes: quote ? { ...rest, [id]: quote } : rest });
  },
}));

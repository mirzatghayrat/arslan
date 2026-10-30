import { create } from "zustand";

/** SB1: the sidebar's open or collapsed state, remembered across launches. App reads it too: with the
 *  sidebar collapsed, the title bar leaves room for the window's traffic lights and the show button. */
export const COLLAPSED_KEY = "arslan_sidebar_collapsed";

function load(): boolean {
  try { return localStorage.getItem(COLLAPSED_KEY) === "1"; } catch { return false; }
}

interface SidebarState { collapsed: boolean; setCollapsed: (collapsed: boolean) => void; reload: () => void }

export const useSidebar = create<SidebarState>((set) => ({
  collapsed: load(),
  setCollapsed: (collapsed) => {
    try { localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0"); } catch { /* storage off: this launch only */ }
    set({ collapsed });
  },
  /** Read the remembered state again (a fresh window does this at start; tests use it as a reload). */
  reload: () => set({ collapsed: load() }),
}));

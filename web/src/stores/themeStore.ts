import { create } from "zustand";

// Fix A: single source of truth — type is derived from the runtime array.
const PALETTES = ["current", "ember", "terminal", "nebula", "slate", "glacier"] as const;
export type Palette = (typeof PALETTES)[number];
export type Mode = "light" | "dark";

interface ThemeState {
  palette: Palette;
  mode: Mode;
  apply: () => void;
  setPalette: (p: Palette) => void;
  setMode: (m: Mode) => void;
  toggleMode: () => void;
}

const STORAGE_KEY = "arslan_theme";

function load(): { palette: Palette; mode: Mode } {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    const palette = PALETTES.includes(raw.palette as Palette) ? raw.palette : "current";
    const mode: Mode = raw.mode === "light" ? "light" : "dark";
    return { palette, mode };
  } catch {
    return { palette: "current", mode: "dark" };
  }
}

function applyToDom(palette: Palette, mode: Mode): void {
  const root = document.documentElement;
  root.dataset.palette = palette;
  root.classList.toggle("dark", mode === "dark");
}

function persist(palette: Palette, mode: Mode): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ palette, mode }));
}

const initial = load();

export const useThemeStore = create<ThemeState>((set, get) => ({
  palette: initial.palette,
  mode: initial.mode,
  apply: () => applyToDom(get().palette, get().mode),
  setPalette: (palette) => { const { mode } = get(); applyToDom(palette, mode); persist(palette, mode); set({ palette }); },
  setMode: (mode) => { const { palette } = get(); applyToDom(palette, mode); persist(palette, mode); set({ mode }); },
  toggleMode: () => get().setMode(get().mode === "dark" ? "light" : "dark"),
}));

// Fix B: guard against non-browser (Node/SSR/test) contexts where document is absent.
// Apply once at module load so there is no flash before React mounts.
if (typeof document !== "undefined") {
  applyToDom(initial.palette, initial.mode);
}

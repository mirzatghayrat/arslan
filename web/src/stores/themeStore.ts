import { create } from "zustand";

// Fix A: single source of truth — type is derived from the runtime array.
const PALETTES = ["current", "ember", "terminal", "nebula", "slate", "glacier"] as const;
export type Palette = (typeof PALETTES)[number];
/** What the user CHOSE. "system" is a standing instruction, not a value. */
export type Mode = "light" | "dark" | "system";
/** What the DOM ends up in. "system" resolves to one of these. */
export type Resolved = "light" | "dark";

/** The OS preference right now. Defaults to dark where matchMedia is absent
 *  (jsdom, SSR) so behaviour matches the previous default rather than flipping
 *  every test to light. */
function systemMode(): Resolved {
  if (typeof window === "undefined" || !window.matchMedia) return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolve(mode: Mode): Resolved {
  return mode === "system" ? systemMode() : mode;
}

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
    const mode: Mode =
      raw.mode === "light" || raw.mode === "system" ? raw.mode : "dark";
    return { palette, mode };
  } catch {
    return { palette: "current", mode: "dark" };
  }
}

function applyToDom(palette: Palette, mode: Mode): void {
  const root = document.documentElement;
  root.dataset.palette = palette;
  root.classList.toggle("dark", resolve(mode) === "dark");
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

// 🔴 "System" is a STANDING instruction, not a one-time read. Without this
// listener the app would match the OS at launch and then stay put when the user
// flips their Mac to light at sunset — which looks exactly like a broken
// setting, since the option's whole promise is that it follows.
if (typeof window !== "undefined" && window.matchMedia) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    const { palette, mode } = useThemeStore.getState();
    if (mode === "system") applyToDom(palette, mode);
  };
  if (mq.addEventListener) mq.addEventListener("change", onChange);
  else mq.addListener(onChange);          // Safari < 14 / older WKWebView
}

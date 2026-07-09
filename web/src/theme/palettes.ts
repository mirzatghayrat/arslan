import type { Palette } from "../stores/themeStore";

export interface PaletteMeta {
  id: Palette;
  nameKey: string;
  // swatch.bg = dark-mode preview tile; swatch.bgLight = light-mode preview tile.
  swatch: { bg: string; bgLight: string; accent: string };
}

export const PALETTES: PaletteMeta[] = [
  { id: "current",  nameKey: "settings.paletteCurrent",  swatch: { bg: "#0A0C10", bgLight: "#FAFBFC", accent: "#D9741A" } },
  { id: "ember",    nameKey: "settings.paletteEmber",    swatch: { bg: "#0C0A09", bgLight: "#FAFAF9", accent: "#F97316" } },
  { id: "terminal", nameKey: "settings.paletteTerminal", swatch: { bg: "#0A0F0D", bgLight: "#F7FAF8", accent: "#22C55E" } },
  { id: "nebula",   nameKey: "settings.paletteNebula",   swatch: { bg: "#0B0A12", bgLight: "#FAF9FE", accent: "#8B5CF6" } },
  { id: "slate",    nameKey: "settings.paletteSlate",    swatch: { bg: "#0B0D10", bgLight: "#F8FAFC", accent: "#3B82F6" } },
  { id: "glacier",  nameKey: "settings.paletteGlacier",  swatch: { bg: "#08110F", bgLight: "#F2FBFA", accent: "#06B6D4" } },
];

export interface ResolvedTokens { background: string; surface: string; foreground: string; mutedForeground: string; primary: string; primaryForeground: string; }
export const PALETTE_TOKENS: Record<Palette, { light: ResolvedTokens; dark: ResolvedTokens }> = {
  current:  { light: { background:"#FAFBFC", surface:"#FFFFFF", foreground:"#0F172A", mutedForeground:"#64748B", primary:"#D9741A", primaryForeground:"#FFFFFF" }, dark: { background:"#0A0C10", surface:"#121622", foreground:"#FFFFFF", mutedForeground:"#94A3B8", primary:"#D9741A", primaryForeground:"#FFFFFF" } },
  ember:    { light: { background:"#FAFAF9", surface:"#FFFFFF", foreground:"#1C1917", mutedForeground:"#78716C", primary:"#C2410C", primaryForeground:"#FFF7ED" }, dark: { background:"#0C0A09", surface:"#1C1917", foreground:"#FAFAF9", mutedForeground:"#A8A29E", primary:"#F97316", primaryForeground:"#3A1404" } },
  terminal: { light: { background:"#F7FAF8", surface:"#FFFFFF", foreground:"#0A1F14", mutedForeground:"#5C7567", primary:"#15803D", primaryForeground:"#F0FDF4" }, dark: { background:"#0A0F0D", surface:"#14201B", foreground:"#ECFDF5", mutedForeground:"#8CA99B", primary:"#22C55E", primaryForeground:"#05330F" } },
  nebula:   { light: { background:"#FAF9FE", surface:"#FFFFFF", foreground:"#1A1430", mutedForeground:"#6B6486", primary:"#6D28D9", primaryForeground:"#F5F3FF" }, dark: { background:"#0B0A12", surface:"#17131F", foreground:"#F5F3FF", mutedForeground:"#A39CB8", primary:"#8B5CF6", primaryForeground:"#1E1340" } },
  slate:    { light: { background:"#F8FAFC", surface:"#FFFFFF", foreground:"#0F172A", mutedForeground:"#64748B", primary:"#1D4ED8", primaryForeground:"#EFF6FF" }, dark: { background:"#0B0D10", surface:"#161A20", foreground:"#F8FAFC", mutedForeground:"#94A3B8", primary:"#3B82F6", primaryForeground:"#0A2540" } },
  glacier:  { light: { background:"#F2FBFA", surface:"#FFFFFF", foreground:"#06201D", mutedForeground:"#5A7E79", primary:"#0E7490", primaryForeground:"#ECFEFF" }, dark: { background:"#08110F", surface:"#102019", foreground:"#ECFEFF", mutedForeground:"#8FB3AD", primary:"#06B6D4", primaryForeground:"#04303A" } },
};

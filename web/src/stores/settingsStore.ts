import { create } from "zustand";
import type { AppSettings } from "../api/client.types";

interface SettingsState {
  settings: AppSettings | null;
  setSettings: (s: AppSettings) => void;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: null,
  setSettings: (settings) => set({ settings }),
}));

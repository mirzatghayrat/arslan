import { create } from "zustand";

/**
 * Client-side user profile. `displayName` is the name shown in the greeting and
 * used as the sender label for the user's own chat bubbles. It is stored ONLY in
 * localStorage (no backend field) — an empty default means a fresh, stranger-safe
 * install greets with NO name. Set it in Settings to personalise.
 */
interface ProfileState {
  displayName: string;
  setDisplayName: (name: string) => void;
}

const STORAGE_KEY = "arslan_profile";

function load(): string {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return typeof raw.displayName === "string" ? raw.displayName : "";
  } catch {
    return "";
  }
}

function persist(displayName: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ displayName }));
  } catch {
    /* non-browser / storage-disabled: keep in-memory only */
  }
}

export const useProfileStore = create<ProfileState>((set) => ({
  displayName: load(),
  setDisplayName: (displayName) => {
    persist(displayName);
    set({ displayName });
  },
}));

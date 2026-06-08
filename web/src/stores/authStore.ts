import { create } from "zustand";

interface AuthState {
  token: string;
  setToken: (token: string) => void;
  clearToken: () => void;
}

const STORAGE_KEY = "arslan_token";

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(STORAGE_KEY) ?? "",
  setToken: (token) => {
    localStorage.setItem(STORAGE_KEY, token);
    set({ token });
  },
  clearToken: () => {
    localStorage.removeItem(STORAGE_KEY);
    set({ token: "" });
  },
}));

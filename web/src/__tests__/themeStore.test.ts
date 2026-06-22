import { describe, it, expect, beforeEach } from "vitest";
import { useThemeStore } from "../stores/themeStore";

// Must reset data-palette + className because the store applies them at module load.
beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("data-palette");
  useThemeStore.setState({ palette: "current", mode: "dark" });
});

it("defaults to current/dark and applies them to <html>", () => {
  useThemeStore.getState().apply();
  expect(document.documentElement.dataset.palette).toBe("current");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
});

it("setPalette updates state, html attr, and persists", () => {
  useThemeStore.getState().setPalette("nebula");
  expect(useThemeStore.getState().palette).toBe("nebula");
  expect(document.documentElement.dataset.palette).toBe("nebula");
  expect(JSON.parse(localStorage.getItem("arslan_theme")!).palette).toBe("nebula");
});

it("setMode toggles the dark class and persists", () => {
  useThemeStore.getState().setMode("light");
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  expect(JSON.parse(localStorage.getItem("arslan_theme")!).mode).toBe("light");
  useThemeStore.getState().setMode("dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
});

it("toggleMode flips mode", () => {
  useThemeStore.setState({ mode: "dark" });
  useThemeStore.getState().toggleMode();
  expect(useThemeStore.getState().mode).toBe("light");
});

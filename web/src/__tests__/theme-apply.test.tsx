import { render } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { useThemeStore } from "../stores/themeStore";
import { ThemeApplier } from "../components/ThemeApplier";

beforeEach(() => { document.documentElement.className = ""; useThemeStore.setState({ palette: "current", mode: "dark" }); });

it("applies the store theme to <html> on mount", () => {
  document.documentElement.classList.remove("dark");
  render(<ThemeApplier />);
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  expect(document.documentElement.dataset.palette).toBe("current");
});

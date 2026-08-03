import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useThemeStore } from "../stores/themeStore";
import { AppearanceSettings } from "../components/AppearanceSettings";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

beforeEach(() => useThemeStore.setState({ palette: "current", mode: "dark" }));

it("renders all 6 palettes and selecting one updates the store", async () => {
  render(<AppearanceSettings />);
  // Scoped to the PALETTE group. The mode selector became a radiogroup too
  // (light / dark / system), so an unscoped query now counts nine — and would
  // have kept "passing" at 9 if someone loosened the number instead.
  const palettes = screen.getByRole("radiogroup", { name: "settings.palette" });
  expect(within(palettes).getAllByRole("radio")).toHaveLength(6);
  await userEvent.click(screen.getByRole("radio", { name: /nebula/i }));
  expect(useThemeStore.getState().palette).toBe("nebula");
});

it("mode toggle flips the store mode", async () => {
  render(<AppearanceSettings />);
  // Three explicit choices now, not a toggle: pick "light" directly.
  await userEvent.click(screen.getByRole("radio", { name: "settings.modeLight" }));
  expect(useThemeStore.getState().mode).toBe("light");
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useThemeStore } from "../stores/themeStore";
import { AppearanceSettings } from "../components/AppearanceSettings";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

beforeEach(() => useThemeStore.setState({ palette: "current", mode: "dark" }));

it("renders all 6 palettes and selecting one updates the store", async () => {
  render(<AppearanceSettings />);
  expect(screen.getAllByRole("radio")).toHaveLength(6);
  await userEvent.click(screen.getByRole("radio", { name: /nebula/i }));
  expect(useThemeStore.getState().palette).toBe("nebula");
});

it("mode toggle flips the store mode", async () => {
  render(<AppearanceSettings />);
  await userEvent.click(screen.getByRole("button", { name: /mode|light|dark|appearance\.mode/i }));
  expect(useThemeStore.getState().mode).toBe("light");
});

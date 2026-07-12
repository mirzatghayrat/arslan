/**
 * AppearanceSection — the "Appearance & Language" settings section.
 *
 * Verifies the section is self-contained and hosts (per spec B1): the display
 * name field (localStorage-backed, local-only), the language Select, and the
 * palette/mode controls (existing <AppearanceSettings/>). Asserts the language
 * change fires the handler, AppearanceSettings is rendered, and the display name
 * input persists to its localStorage mechanism (profileStore).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

import AppearanceSection from "../components/settings/AppearanceSection";
import { useProfileStore } from "../stores/profileStore";

type Props = React.ComponentProps<typeof AppearanceSection>;

function setup(overrides: Partial<Props> = {}) {
  const props: Props = {
    language: "en",
    onLanguageChange: vi.fn(),
    ...overrides,
  };
  render(<AppearanceSection {...props} />);
  return props;
}

describe("AppearanceSection", () => {
  beforeEach(() => {
    localStorage.clear();
    useProfileStore.setState({ displayName: "" });
    vi.clearAllMocks();
  });

  it("renders the language Select", () => {
    setup();
    expect(document.getElementById("settings-language")).not.toBeNull();
  });

  it("fires onLanguageChange('zh') when Chinese is selected", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(document.getElementById("settings-language") as HTMLButtonElement);
    const zh = screen
      .getAllByRole("option")
      .find((o) => /简体中文/.test(o.textContent ?? ""));
    expect(zh).toBeTruthy();
    await user.click(zh as HTMLElement);
    expect(props.onLanguageChange).toHaveBeenCalledWith("zh");
  });

  it("renders the existing AppearanceSettings (palette + mode)", () => {
    setup();
    // AppearanceSettings renders the palette label + a radiogroup of palettes.
    expect(screen.getByText("settings.palette")).toBeInTheDocument();
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
  });

  it("renders the display name input and persists edits to localStorage", () => {
    setup();
    const input = document.getElementById("settings-display-name") as HTMLInputElement;
    expect(input).not.toBeNull();
    fireEvent.change(input, { target: { value: "Alice" } });
    // profileStore is the localStorage mechanism (key "arslan_profile").
    expect(useProfileStore.getState().displayName).toBe("Alice");
    expect(localStorage.getItem("arslan_profile")).toContain("Alice");
  });
});

/**
 * SettingsShell tests — the System Settings side-nav shell.
 *
 * Strategy: mock react-i18next to a passthrough `t` so nav labels render as
 * their i18n keys (e.g. `settings.navSearch`) and the coming-soon / placeholder
 * hints render as their keys. SettingsShell is a pure layout component: it takes
 * an active section, a section-change callback, and a `children` map of section
 * id → ReactNode, and renders the left/top nav + the active section's node.
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import SettingsShell from "../components/settings/SettingsShell";
import {
  SETTINGS_SECTIONS,
  type SettingsSectionId,
} from "../components/settings/sectionRegistry";

const CHILDREN: Partial<Record<SettingsSectionId, React.ReactNode>> = {
  providers: <div data-testid="child-providers">providers-body</div>,
  search: <div data-testid="child-search">search-body</div>,
  appearance: <div data-testid="child-appearance">appearance-body</div>,
  access: <div data-testid="child-access">access-body</div>,
  memory: <div data-testid="child-memory">memory-body</div>,
  advanced: <div data-testid="child-advanced">advanced-body</div>,
};

const REAL_IDS: SettingsSectionId[] = [
  "providers", "search", "appearance", "access", "memory", "advanced",
];
const PLACEHOLDER_IDS: SettingsSectionId[] = ["scheduled", "usage"];

describe("SettingsShell", () => {
  it("registry exposes the 6 real sections + 2 placeholders", () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual([
      ...REAL_IDS, ...PLACEHOLDER_IDS,
    ]);
    expect(SETTINGS_SECTIONS.filter((s) => s.placeholder).map((s) => s.id))
      .toEqual(PLACEHOLDER_IDS);
  });

  it("renders all 6 real nav items + 2 placeholder items", () => {
    render(
      <SettingsShell activeSection="providers" onSectionChange={vi.fn()}>
        {CHILDREN}
      </SettingsShell>,
    );
    for (const id of [...REAL_IDS, ...PLACEHOLDER_IDS]) {
      expect(screen.getByTestId(`settings-nav-${id}`)).toBeInTheDocument();
    }
  });

  it("placeholder nav items show the coming-soon sub-label", () => {
    render(
      <SettingsShell activeSection="providers" onSectionChange={vi.fn()}>
        {CHILDREN}
      </SettingsShell>,
    );
    // One coming-soon sub-label per placeholder section (scheduled + usage).
    expect(screen.getAllByText("settings.navComingSoon")).toHaveLength(
      PLACEHOLDER_IDS.length,
    );
  });

  it("clicking the search nav item calls onSectionChange('search')", async () => {
    const onSectionChange = vi.fn();
    const user = userEvent.setup();
    render(
      <SettingsShell activeSection="providers" onSectionChange={onSectionChange}>
        {CHILDREN}
      </SettingsShell>,
    );
    await user.click(screen.getByTestId("settings-nav-search"));
    expect(onSectionChange).toHaveBeenCalledWith("search");
  });

  it("shows only the active section's child (providers visible, search absent)", () => {
    render(
      <SettingsShell activeSection="providers" onSectionChange={vi.fn()}>
        {CHILDREN}
      </SettingsShell>,
    );
    expect(screen.getByTestId("child-providers")).toBeInTheDocument();
    expect(screen.queryByTestId("child-search")).toBeNull();
  });

  it("switches the visible child when activeSection changes", () => {
    const { rerender } = render(
      <SettingsShell activeSection="providers" onSectionChange={vi.fn()}>
        {CHILDREN}
      </SettingsShell>,
    );
    expect(screen.getByTestId("child-providers")).toBeInTheDocument();
    rerender(
      <SettingsShell activeSection="memory" onSectionChange={vi.fn()}>
        {CHILDREN}
      </SettingsShell>,
    );
    expect(screen.getByTestId("child-memory")).toBeInTheDocument();
    expect(screen.queryByTestId("child-providers")).toBeNull();
  });

  it("renders the placeholder hint when active section is a placeholder", () => {
    render(
      <SettingsShell activeSection="scheduled" onSectionChange={vi.fn()}>
        {CHILDREN}
      </SettingsShell>,
    );
    expect(screen.getByTestId("settings-placeholder")).toBeInTheDocument();
    expect(screen.getByText("settings.placeholderHint")).toBeInTheDocument();
    // No real child mounts for a placeholder section.
    expect(screen.queryByTestId("child-providers")).toBeNull();
  });

  it("renders the placeholder hint when a real section has no child", () => {
    render(
      <SettingsShell activeSection="memory" onSectionChange={vi.fn()}>
        {{ providers: CHILDREN.providers }}
      </SettingsShell>,
    );
    expect(screen.getByTestId("settings-placeholder")).toBeInTheDocument();
    expect(screen.queryByTestId("child-memory")).toBeNull();
  });
});

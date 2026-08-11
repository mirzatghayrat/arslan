/**
 * SettingsShell tests — the Settings side-nav shell after the D3 redesign.
 *
 * Strategy unchanged: mock react-i18next to a passthrough `t` so labels render
 * as their i18n keys. SettingsShell stays a pure layout component — active
 * section, a change callback, and a `children` map of section id → ReactNode.
 *
 * What changed, and what these tests still have to guarantee:
 *  - eight sections in three groups, no placeholders
 *    (seven until `modelroles` was added — the per-task model slots shipped on
 *     the backend with no surface, so the nav gained a real section, not a
 *     placeholder: FIELD_HOMES gives it five fields)
 *  - search filters the nav, over the registry rather than a second list
 * The old file's guarantees that SURVIVE the redesign (only the active child
 * mounts, switching swaps it, clicking calls back, one button per section) are
 * kept verbatim — a redesign is only safe if what held before still holds.
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
  SETTINGS_GROUPS,
  type SettingsSectionId,
} from "../components/settings/sectionRegistry";

const CHILDREN: Partial<Record<SettingsSectionId, React.ReactNode>> = {
  models: <div data-testid="child-models">models-body</div>,
  search: <div data-testid="child-search">search-body</div>,
  appearance: <div data-testid="child-appearance">appearance-body</div>,
  access: <div data-testid="child-access">access-body</div>,
  memory: <div data-testid="child-memory">memory-body</div>,
  automation: <div data-testid="child-automation">automation-body</div>,
  advanced: <div data-testid="child-advanced">advanced-body</div>,
};

const IDS: SettingsSectionId[] = [
  "models", "modelroles", "search", "appearance", "memory", "automation", "access", "advanced",
];

const shell = (active: SettingsSectionId, onChange = vi.fn()) =>
  render(
    <SettingsShell activeSection={active} onSectionChange={onChange}>
      {CHILDREN}
    </SettingsShell>,
  );

describe("SettingsShell", () => {
  it("exposes eight sections in nav order, with no placeholders", () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual(IDS);
    // Discriminating: renaming a placeholder rather than deleting it would keep
    // the count at seven only if something real were dropped to make room.
    expect(SETTINGS_SECTIONS.map((s) => s.id)).not.toContain("scheduled");
    expect(SETTINGS_SECTIONS.map((s) => s.id)).not.toContain("usage");
  });

  it("renders exactly one button per section — no duplicated DOM at any width", () => {
    shell("models");
    for (const id of IDS) {
      expect(screen.getAllByTestId(`settings-nav-${id}`)).toHaveLength(1);
    }
  });

  it("renders a heading per group", () => {
    shell("models");
    for (const g of SETTINGS_GROUPS) {
      expect(screen.getByText(g.labelKey)).toBeInTheDocument();
    }
  });

  it("clicking a nav item calls onSectionChange with its id", async () => {
    const onSectionChange = vi.fn();
    const user = userEvent.setup();
    shell("models", onSectionChange);
    await user.click(screen.getByTestId("settings-nav-automation"));
    expect(onSectionChange).toHaveBeenCalledWith("automation");
  });

  it("shows only the active section's child", () => {
    shell("models");
    expect(screen.getByTestId("child-models")).toBeInTheDocument();
    expect(screen.queryByTestId("child-search")).toBeNull();
  });

  it("switches the visible child when activeSection changes", () => {
    const { rerender } = shell("models");
    expect(screen.getByTestId("child-models")).toBeInTheDocument();
    rerender(
      <SettingsShell activeSection="memory" onSectionChange={vi.fn()}>
        {CHILDREN}
      </SettingsShell>,
    );
    expect(screen.getByTestId("child-memory")).toBeInTheDocument();
    expect(screen.queryByTestId("child-models")).toBeNull();
  });
});

describe("settings search", () => {
  it("filters the nav down to matching sections", async () => {
    const user = userEvent.setup();
    shell("models");
    await user.type(screen.getByTestId("settings-search"), "memory");
    expect(screen.getByTestId("settings-nav-memory")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-nav-advanced")).toBeNull();
  });

  it("hides the group headings while filtering", async () => {
    // With two of seven entries left, three headings are more chrome than content.
    const user = userEvent.setup();
    shell("models");
    await user.type(screen.getByTestId("settings-search"), "memory");
    for (const g of SETTINGS_GROUPS) {
      expect(screen.queryByText(g.labelKey)).toBeNull();
    }
  });

  it("matches the translated label, not only the raw id", async () => {
    // Discriminating: filtering on `s.id` alone would pass every other search
    // test here, because the mocked `t` returns the key and the ids happen to
    // appear inside the keys. This searches for text that is ONLY in the label.
    const user = userEvent.setup();
    shell("models");
    await user.type(screen.getByTestId("settings-search"), "navaccess");
    expect(screen.getByTestId("settings-nav-access")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-nav-models")).toBeNull();
  });

  it("says so when nothing matches, rather than showing an empty nav", async () => {
    const user = userEvent.setup();
    shell("models");
    await user.type(screen.getByTestId("settings-search"), "zzzzz");
    expect(screen.getByTestId("settings-search-empty")).toBeInTheDocument();
  });

  it("keeps the active section's content mounted while filtering", async () => {
    // Filtering the NAV must not unmount what you were editing — a half-typed
    // field disappearing because you searched for something else is data loss.
    const user = userEvent.setup();
    shell("models");
    await user.type(screen.getByTestId("settings-search"), "memory");
    expect(screen.getByTestId("child-models")).toBeInTheDocument();
  });
});

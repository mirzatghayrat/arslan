/**
 * SettingsShell tests — the Settings side-nav shell after the D3 redesign.
 *
 * Strategy unchanged: mock react-i18next to a passthrough `t` so labels render
 * as their i18n keys. SettingsShell stays a pure layout component — active
 * section, a change callback, and a `children` map of section id → ReactNode.
 *
 * What changed, and what these tests still have to guarantee:
 *  - 0.1.55 §11: seven flat sections (general, models, abilities, background,
 *    memory, connections, about), no group headings, no placeholders
 *  - before that: eleven sections in three groups
 *    (nine until `proactive` was added in 0.1.47 — what Arslan looks out for; free to
 *     run, so not in automation, while its one spending control is)
 *    (eight until `desktop` was added in 0.1.41 — resident-mode switches that are
 *     on by default and spend nothing, so they could not honestly live in automation)
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
  general: <div data-testid="child-general">general-body</div>,
  models: <div data-testid="child-models">models-body</div>,
  abilities: <div data-testid="child-abilities">abilities-body</div>,
  background: <div data-testid="child-background">background-body</div>,
  memory: <div data-testid="child-memory">memory-body</div>,
  connections: <div data-testid="child-connections">connections-body</div>,
  about: <div data-testid="child-about">about-body</div>,
};

const IDS: SettingsSectionId[] = [
  "general", "models", "abilities", "background", "memory", "connections", "about",
];

const shell = (active: SettingsSectionId, onChange = vi.fn()) =>
  render(
    <SettingsShell activeSection={active} onSectionChange={onChange}>
      {CHILDREN}
    </SettingsShell>,
  );

describe("SettingsShell", () => {
  it("allows desktop labels to wrap while preserving compact mobile chips", () => {
    shell("general");
    for (const id of IDS) {
      const button = screen.getByTestId(`settings-nav-${id}`);
      expect(button).toHaveClass("whitespace-nowrap", "md:whitespace-normal");
      expect(button.querySelector("span.flex")).toHaveClass("min-w-0", "md:break-words");
    }
  });
  it("provides a single settings sidebar with a working return action", async () => {
    const onBack = vi.fn();
    render(<SettingsShell activeSection="models" onSectionChange={vi.fn()} onBack={onBack}>{CHILDREN}</SettingsShell>);
    expect(screen.getAllByTestId("settings-sidebar")).toHaveLength(1);
    await userEvent.click(screen.getByTestId("settings-back"));
    expect(onBack).toHaveBeenCalledOnce();
  });
  it("exposes seven sections in nav order, with no placeholders", () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual(IDS);
    // Discriminating: renaming a placeholder rather than deleting it would keep
    // the count only if something real were dropped to make room.
    expect(SETTINGS_SECTIONS.map((s) => s.id)).not.toContain("scheduled");
    expect(SETTINGS_SECTIONS.map((s) => s.id)).not.toContain("usage");
  });

  it("renders exactly one button per section — no duplicated DOM at any width", () => {
    shell("models");
    for (const id of IDS) {
      expect(screen.getAllByTestId(`settings-nav-${id}`)).toHaveLength(1);
    }
  });

  it("renders no group headings — seven entries are read at a glance", () => {
    shell("models");
    expect(SETTINGS_GROUPS).toEqual([]);
    expect(screen.queryByText("settings.navRegion")).toBeNull();
  });

  it("clicking a nav item calls onSectionChange with its id", async () => {
    const onSectionChange = vi.fn();
    const user = userEvent.setup();
    shell("models", onSectionChange);
    await user.click(screen.getByTestId("settings-nav-background"));
    expect(onSectionChange).toHaveBeenCalledWith("background");
  });

  it("shows only the active section's child", () => {
    shell("models");
    expect(screen.getByTestId("child-models")).toBeInTheDocument();
    expect(screen.queryByTestId("child-general")).toBeNull();
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
    expect(screen.queryByTestId("settings-nav-models")).toBeNull();
    expect(screen.queryByTestId("settings-nav-about")).toBeNull();
  });

  it("matches the translated label, not only the raw id", async () => {
    // Discriminating: filtering on `s.id` alone would pass every other search
    // test here, because the mocked `t` returns the key and the ids happen to
    // appear inside the keys. This searches for text that is ONLY in the label.
    const user = userEvent.setup();
    shell("models");
    await user.type(screen.getByTestId("settings-search"), "navconnections");
    expect(screen.getByTestId("settings-nav-connections")).toBeInTheDocument();
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


// 0.1.46 layout: the window never scrolls as a whole. The left nav is compact and
// stays put; only the right pane scrolls. jsdom has no layout, so this pins the
// structure that makes it so: exactly one scroll container, and the nav is not
// inside it (before, one outer scroller carried the nav away with the content).
describe("SettingsShell layout", () => {
  const scrollers = (root: Element) => [root, ...Array.from(root.querySelectorAll("*"))]
    .filter((el) => /(^|\s)overflow-y-auto(\s|$)/.test(el.getAttribute("class") ?? ""));

  it("has one scrolling region — the content pane — and the nav is outside it", () => {
    const { container } = shell("models");
    const content = screen.getByTestId("settings-content");
    const sidebar = screen.getByTestId("settings-sidebar");
    expect(content.className).toMatch(/overflow-y-auto/);
    expect(content.contains(sidebar)).toBe(false);
    // the desktop nav itself scrolls only as a fallback on a very short window
    expect(sidebar.className).toMatch(/md:overflow-y-auto/);
    expect(scrollers(container).filter((el) => el !== sidebar)).toEqual([content]);
  });

  it("fills the window instead of growing past it", () => {
    const { container } = shell("models");
    expect((container.firstElementChild as HTMLElement).className).toMatch(/min-h-0/);
    expect((container.firstElementChild as HTMLElement).className).not.toMatch(/\bmin-h-screen\b/);
  });

  it("restarts the slide-in on the content when the section changes", () => {
    const { rerender } = shell("models");
    const first = screen.getByTestId("child-models").parentElement!;
    expect(first.className).toMatch(/settings-pane-in/);
    rerender(<SettingsShell activeSection="general" onSectionChange={vi.fn()}>{CHILDREN}</SettingsShell>);
    const second = screen.getByTestId("child-general").parentElement!;
    expect(second).not.toBe(first);          // a new element: the animation plays again
  });

  it("uses one quiet type size for every entry", () => {
    shell("models");
    for (const id of IDS) {
      const label = screen.getByTestId(`settings-nav-${id}`).querySelector("span > span")!;
      expect(label.className).toMatch(/text-\[13px\]/);
    }
  });
});

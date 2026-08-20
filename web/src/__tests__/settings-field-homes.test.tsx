/**
 * Gate item ③ — the redesign must not lose a control.
 *
 * The mock's §03 promised "every existing field has a new home". A promise in
 * prose is checked by a person re-reading two screens; this checks it as data.
 *
 * `FIELD_HOMES` is the contract. These tests hold it to three things a prose
 * table cannot be held to: every entry names a section that exists, every
 * section that claims fields renders them, and — the one that actually bites —
 * nothing that used to be reachable became unreachable.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import AdvancedSection from "../components/settings/AdvancedSection";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import {
  SETTINGS_SECTIONS, SETTINGS_GROUPS, FIELD_HOMES, sectionsByGroup,
  type SettingsSectionId,
} from "../components/settings/sectionRegistry";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (p: string) => readFileSync(resolve(SRC, p), "utf8");

/** Dot-path lookup into the locale JSON. */
function hasKey(key: string): boolean {
  let node: unknown = en;
  for (const part of key.split(".")) {
    if (node == null || typeof node !== "object") return false;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string";
}

describe("settings section registry", () => {
  it("every field's home is a section that exists", () => {
    const ids = new Set<string>(SETTINGS_SECTIONS.map((s) => s.id));
    for (const [field, home] of Object.entries(FIELD_HOMES)) {
      expect(ids.has(home), `${field} claims section "${home}", which is not in the nav`).toBe(true);
    }
  });

  it("every section holds at least one field", () => {
    // Discriminating: a nav entry with nothing behind it is exactly what the
    // deleted `scheduled`/`usage` placeholders were. Adding one back would
    // pass every other test in this file.
    const homed = new Set(Object.values(FIELD_HOMES));
    for (const s of SETTINGS_SECTIONS) {
      expect(homed.has(s.id), `section "${s.id}" is a nav entry with no fields`).toBe(true);
    }
  });

  it("the placeholder sections are gone, not renamed", () => {
    const ids = SETTINGS_SECTIONS.map((s) => s.id) as string[];
    expect(ids).not.toContain("scheduled");
    expect(ids).not.toContain("usage");
    // …and the pointer they existed to provide survives.
    expect(FIELD_HOMES["automation.diagnostics_link"]).toBe("automation");
  });

  it("every nav label and group label resolves to a real string", () => {
    for (const g of SETTINGS_GROUPS) {
      expect(hasKey(g.labelKey), `${g.labelKey} missing from en.json`).toBe(true);
    }
    for (const s of SETTINGS_SECTIONS) {
      expect(hasKey(s.labelKey), `${s.labelKey} missing from en.json`).toBe(true);
      if (s.hintKey) expect(hasKey(s.hintKey), `${s.hintKey} missing`).toBe(true);
    }
  });

  it("grouping covers every section exactly once", () => {
    const grouped = sectionsByGroup().flatMap((g) => g.sections.map((s) => s.id));
    expect(grouped.sort()).toEqual(SETTINGS_SECTIONS.map((s) => s.id).sort());
  });

  it("everything that can spend money is in one section", () => {
    // The reason `automation` exists. Split across sections is how someone
    // turns on the second spend control without seeing the first one's warning.
    const spenders = ["evolution.auto", "evolution.max_dispatches", "curation.enabled"];
    for (const f of spenders) {
      expect(FIELD_HOMES[f], `${f} is not in automation`).toBe("automation");
    }
  });
});

describe("no control was lost in the redesign", () => {
  it("the curation toggle exists in the UI, not only in the API", () => {
    // The whole point of the four-angle sweep. `curation_enabled` shipped in
    // SettingsIn/SettingsOut and is documented as spending, and the frontend
    // had ZERO references to it — a background loop that spends, with no way
    // for the user to see or stop it. A component-only reading of the settings
    // code could never have found that, because there was nothing to read.
    expect(FIELD_HOMES["curation.enabled"]).toBe("automation");
    const src = read("components/settings/AutomationSection.tsx");
    expect(src).toMatch(/curationEnabled/);
  });

  it("the spend controls moved out of Advanced and left nothing behind", () => {
    const advanced = read("components/settings/AdvancedSection.tsx");
    expect(advanced).not.toMatch(/labelEvolutionAuto/);
    expect(advanced).not.toMatch(/labelEvolutionMaxDispatches/);
  });

  it("…and Advanced still SHOWS what it was supposed to keep", () => {
    // Rendered, not grepped. The grep version of this passed a mutation that
    // deleted the spawn-mode HEADING, because the same key survived in an
    // `ariaLabel` further down the file — a source match proves the string is
    // in the file, not that a user can see it.
    render(
      <AdvancedSection
        telemetry={false} onTelemetryChange={() => {}}
        orchestratorShellEnabled={false} onOrchestratorShellChange={() => {}}
        shellConfirmPolicy="ask_all" onShellConfirmPolicyChange={() => {}}
        workspaceDir="" onWorkspaceDirChange={() => {}}
        spawnMode="auto" onSpawnModeChange={() => {}}
      />,
    );
    for (const kept of ["settings.labelTelemetry", "settings.labelOrchestratorShell",
                        "settings.labelSpawnMode"]) {
      expect(screen.getByRole("heading", { name: kept }),
             `Advanced no longer shows ${kept}`).toBeTruthy();
    }
  });

  it("the Diagnostics link is actually WIRED, not just accepted as a prop", () => {
    // Found by looking at the running app, not by any of the 1150 tests: the
    // button is conditional on `onOpenDiagnostics`, App.tsx never passed it, so
    // the replacement for the two deleted nav entries silently did not exist.
    // A prop that nobody passes is indistinguishable from a feature nobody built.
    const app = read("App.tsx");
    expect(app).toMatch(/<SettingsScreen[\s\S]*?onOpenDiagnostics=/);
    expect(read("components/settings/AutomationSection.tsx"))
      .toMatch(/automation-open-diagnostics/);
  });

  it("the page subtitle does not name sections that no longer exist", () => {
    // It read "Configure providers, search, appearance, memory, and advanced
    // options" — two of those names died with the redesign and Automation was
    // missing. Copy that lists the nav is copy that goes stale when the nav moves.
    // Checked in every locale, because the stale English was translated five
    // times over and each copy went stale with it.
    const DEAD = ["providers", "scheduled", "usage"];
    const locales: Record<string, unknown>[] = [en, zh, ja, es, de, fr];
    for (const loc of locales) {
      const lore = (loc as Record<string, Record<string, string>>).settings.headerLore;
      for (const dead of DEAD) {
        expect(lore.toLowerCase(), `subtitle still names the removed "${dead}" section`)
          .not.toContain(dead);
      }
    }
  });

  it("the MCP server toggle moved to access, not into limbo", () => {
    expect(FIELD_HOMES["access.mcp_server_enabled"]).toBe("access");
    expect(read("components/settings/AdvancedSection.tsx")).not.toMatch(/labelMcpServer/);
    expect(read("components/AccessTokenSettings.tsx")).toMatch(/labelMcpServer/);
  });
});

describe("the settings chrome says nothing in a language nobody chose", () => {
  it("the page title is a key, and does not call this page Diagnostics", () => {
    // It read "System Diagnostics & Configuration" — hardcoded English, on the
    // SETTINGS page, naming a different screen. Both halves were wrong.
    const src = read("components/SettingsScreen.tsx");
    expect(src).not.toContain("System Diagnostics & Configuration");
    expect(src).toMatch(/t\(['"]settings\.pageTitle['"]\)/);
    expect(hasKey("settings.pageTitle")).toBe(true);
  });

  it("the offline banner body is a key", () => {
    const src = read("components/SettingsScreen.tsx");
    expect(src).not.toContain("Settings could not be loaded from the server");
    expect(hasKey("settings.offlineBody")).toBe(true);
  });
});

describe("settings search", () => {
  it("searches the registry rather than a second hand-kept list", () => {
    // A search index maintained separately from the nav is one that goes stale
    // the first time a section is added. This asserts the source, not the feature.
    const src = read("components/settings/SettingsShell.tsx");
    expect(src).toMatch(/SETTINGS_SECTIONS|sectionsByGroup/);
    expect(src).toMatch(/query|search/i);
  });
});

/** Sections the shell must be able to render (used by the shell's own tests). */
export const ALL_SECTIONS: SettingsSectionId[] = SETTINGS_SECTIONS.map((s) => s.id);

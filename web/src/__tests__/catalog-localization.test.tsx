import { afterEach, describe, expect, it } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { catalogMessages } from "../locales/catalog";
import { catalogText } from "../lib/catalogDisplay";

// C2f: the tools tab that rendered these names is gone (ToolsView); the helper and the six-language
// parity of the catalog copy stay tested here.
afterEach(() => { void i18n.changeLanguage("en"); });

describe("catalog display localization", () => {
  it("falls back to the source text for custom or unknown keys", () => {
    expect(catalogText(i18n.t.bind(i18n), undefined, "My custom name")).toBe("My custom name");
    expect(catalogText(i18n.t.bind(i18n), "catalogUI.future.name", "Future name")).toBe("Future name");
    expect(catalogText(i18n.t.bind(i18n), "settings.title", "External text")).toBe("External text");
  });

  it("includes every field in all six languages", () => {
    for (const language of SUPPORTED_LANGUAGES) {
      expect(Object.keys(catalogMessages[language]).sort()).toEqual(Object.keys(catalogMessages.en).sort());
      for (const entry of Object.values(catalogMessages[language])) {
        expect(Object.keys(entry).sort()).toEqual(["description", "name"]);
        expect(entry.name.trim()).not.toBe("");
        expect(entry.description.trim()).not.toBe("");
      }
    }
  });
});

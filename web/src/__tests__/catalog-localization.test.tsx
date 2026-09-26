import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { catalogMessages } from "../locales/catalog";
import { uiMessages } from "../locales/ui";
import { catalogText } from "../lib/catalogDisplay";
import CapabilityCatalog from "../components/CapabilityCatalog";

vi.mock("../api/client", () => ({ api: {
  getRegistry: vi.fn(async () => ({ skills: [], toolsets: [{
    key: "file_operations", name: "File Operations", description: "Built-in source description",
    name_key: "catalogUI.file_operations.name", description_key: "catalogUI.file_operations.description",
    tier: "safe", status: "wired", assignable: true, tools: [],
    degraded: true, warning_code: "unsandboxed_python", warning: "Legacy source warning",
  }] })),
  listSpawns: vi.fn(async () => []),
} }));
afterEach(() => { cleanup(); void i18n.changeLanguage("en"); });

describe("catalog display localization", () => {
  it.each(SUPPORTED_LANGUAGES)("renders and searches translated built-ins in %s", async language => {
    await i18n.changeLanguage(language);
    render(<CapabilityCatalog kind="tools" />);
    const copy = catalogMessages[language].file_operations;
    expect(await screen.findByText(copy.name)).toBeInTheDocument();
    expect(screen.getByText(copy.description)).toBeInTheDocument();
    expect(screen.getByText(uiMessages[language].unsandboxedPython)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: copy.name } });
    expect(screen.getByText(copy.name)).toBeInTheDocument();
    expect(screen.queryByText("Legacy source warning")).not.toBeInTheDocument();
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

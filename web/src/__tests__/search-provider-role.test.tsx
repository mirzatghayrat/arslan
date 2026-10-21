/**
 * 0.1.63 D5: a chosen Tavily / SearXNG is either the only search or a backup to the conversation model's own
 * search. What is ON SCREEN, what a click saves, and what a new choice defaults to, end to end.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import en from "../locales/en.json";
import { uiMessages } from "../locales/ui";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const hit = key.split(".").reduce<unknown>(
        (node, part) =>
          node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined,
        { ...en, ui: uiMessages.en } as unknown,
      );
      if (typeof hit !== "string" || !hit.trim()) throw new Error(`missing locale string: ${key}`);
      return hit;
    },
  }),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  testSearchInstance: vi.fn(),
}));

import SearchToolsSection, { isChosenService, roleForNewProvider } from "../components/settings/SearchToolsSection";

const base = {
  searchProvider: "tavily",
  searchProviders: ["duckduckgo", "tavily", "searxng"],
  onSearchProviderChange: () => {},
  searchKey: "",
  onSearchKeyChange: () => {},
  githubToken: "",
  onGithubTokenChange: () => {},
};
const role = () => screen.queryByRole("button", { name: uiMessages.en.searchRoleLabel })
  ?? screen.queryByLabelText(uiMessages.en.searchRoleLabel);

describe("the role control", () => {
  it("is absent when no service is chosen, and the note about the model's own search shows", () => {
    for (const provider of ["", "duckduckgo"]) {
      const { unmount } = render(<SearchToolsSection {...base} searchProvider={provider} />);
      expect(role()).toBeNull();
      expect(screen.getByTestId("search-native-note").textContent).toBe(uiMessages.en.searchNativeNote);
      unmount();
    }
  });

  it("shows a choice saved before D5 (\"\") as the only search, without the model-search note", () => {
    render(<SearchToolsSection {...base} searchProviderRole="" />);
    expect(role()).not.toBeNull();
    expect(screen.getByText(uiMessages.en.searchRoleOnly)).toBeTruthy();
    expect(screen.queryByTestId("search-native-note")).toBeNull();   // only = the model's search is not used
  });

  it("shows backup as backup, with the note", () => {
    render(<SearchToolsSection {...base} searchProvider="searxng" searchProviderRole="backup" />);
    expect(screen.getByText(uiMessages.en.searchRoleBackup)).toBeTruthy();
    expect(screen.getByTestId("search-native-note")).toBeTruthy();
  });

  it("saves what the user picks", async () => {
    const onRole = vi.fn();
    render(<SearchToolsSection {...base} searchProviderRole="" onSearchProviderRoleChange={onRole} />);
    await userEvent.click(screen.getByText(uiMessages.en.searchRoleOnly));
    await userEvent.click(screen.getByRole("option", { name: uiMessages.en.searchRoleBackup }));
    expect(onRole).toHaveBeenCalledWith("backup");
  });
});

describe("a new choice", () => {
  it("defaults to backup, keeps an explicit only, and saves no role for no service", () => {
    expect(roleForNewProvider("tavily", "")).toEqual({ searchProviderRole: "backup" });
    expect(roleForNewProvider("searxng", undefined)).toEqual({ searchProviderRole: "backup" });
    expect(roleForNewProvider("searxng", "backup")).toEqual({ searchProviderRole: "backup" });
    expect(roleForNewProvider("tavily", "only")).toEqual({ searchProviderRole: "only" });
    expect(roleForNewProvider("duckduckgo", "only")).toEqual({});
    expect(isChosenService(" Tavily ")).toBe(true);
    expect(isChosenService("DuckDuckGo")).toBe(false);
  });
});

describe("the wiring from backend to screen and back", () => {
  it("carries search_provider_role both ways", async () => {
    const { toUiSettings, toBackendSettings } = await import("../api/adapters");
    expect((toUiSettings({ search_provider_role: "backup" } as never) as Record<string, unknown>).searchProviderRole)
      .toBe("backup");
    expect((toUiSettings({} as never) as Record<string, unknown>).searchProviderRole).toBe("");
    expect((toBackendSettings({ searchProviderRole: "only" } as never) as Record<string, unknown>).search_provider_role)
      .toBe("only");
  });

  it("SettingsScreen passes the role down and saves it with a newly picked provider", async () => {
    // A prop the host never passes is not a type error when it is optional; only the call site shows it.
    const text = (await import("../components/SettingsScreen?raw")).default as string;
    const call = text.slice(text.indexOf("<SearchToolsSection"));
    const block = call.slice(0, call.indexOf("/>"));
    expect(block).toMatch(/searchProviderRole=\{localSettings\.searchProviderRole/);
    expect(block).toMatch(/onSearchProviderRoleChange=\{\(v\) => saveField\(\{ searchProviderRole: v \}\)\}/);
    expect(block).toMatch(/saveField\(\{ searchProvider: v, \.\.\.roleForNewProvider\(v, localSettings\.searchProviderRole\) \}\)/);
  });
});

describe("the activity line for a blocked search", () => {
  it("says blocked for every search_blocked error, and not for other failures", async () => {
    const { humanizeStep } = await import("../lib/toolHumanize");
    const t = (key: string) => (key === "ui.searchBlocked" ? uiMessages.en.searchBlocked : key);
    const line = (resultSummary: string) =>
      humanizeStep({ tool: "web_search", argsSummary: "", resultSummary, status: "error" } as never, t as never);
    expect(line("search blocked: tavily refused the query (http 429). This is not 'no results'"))
      .toBe(uiMessages.en.searchBlocked);
    expect(line("search blocked: web search is unavailable right now — duckduckgo: blocked (challenge)"))
      .toBe(uiMessages.en.searchBlocked);
    expect(line("web search is unavailable right now — anthropic: http 500; duckduckgo: blocked (challenge)"))
      .not.toBe(uiMessages.en.searchBlocked);
    expect(line("search failed: key-rejected — the search key was rejected: re-enter it in Settings"))
      .toBe("activity.search_fail_key");
  });
});

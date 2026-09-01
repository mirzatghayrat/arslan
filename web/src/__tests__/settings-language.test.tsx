/**
 * SettingsScreen language selector wiring tests.
 *
 * Asserts the language <Select> (1) offers all 6 supported languages, and
 * (2) actually switches the UI language via i18n.changeLanguage when changed.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisted spy so we can assert changeLanguage was called from the component.
const changeLanguage = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage, language: "en" },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
    embeddingStatus: vi.fn().mockResolvedValue(null),
    getAccessToken: vi.fn().mockResolvedValue({ token_required: false, token: null }),
    resetAccessToken: vi.fn().mockResolvedValue({ token: "new-token" }),
  },
  API_BASE: "",
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: vi.fn().mockResolvedValue([]),
  addProviderConfig: vi.fn().mockResolvedValue({}),
  updateProviderConfig: vi.fn().mockResolvedValue({}),
  setPrimaryProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  deleteProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: Object.assign(
    (sel: (s: { token: string; setToken: (t: string) => void }) => unknown) =>
      sel({ token: "", setToken: () => {} }),
    { getState: () => ({ token: "", setToken: () => {} }) },
  ),
}));

import SettingsScreen from "../components/SettingsScreen";
import type { AppSettings } from "../types";
import type { ProviderOption } from "../api/client.types";

const defaultSettings: AppSettings = {
  searchProvider: "tavily",
  searchBaseUrl: '',
  apiKeySearch: "tvly-••••",
  githubToken: "",
  language: "en",
  theme: "dark",
  telemetry: false,
  spawnMode: "auto",
  llmStrategy: "single",
  distillOnSessionEnd: true,
  orchestratorShellEnabled: false,
  shellConfirmPolicy: "ask_all", workspaceDir: "", heartbeatEnabled: false, heartbeatChecklist: "", lanDiscoveryEnabled: false, sshEnabled: false, defaultReadEnabled: true, voiceOutputEnabled: false, voiceInputLocale: "",
  mcpServerEnabled: false,
};

const providers: ProviderOption[] = [
  { key: "anthropic", label: "Anthropic", base_url: "https://api.anthropic.com", default_model: "claude-sonnet-4-5", native: true, models: ["claude-sonnet-4-5"] },
];

function renderSettings(overrides: Partial<AppSettings> = {}) {
  render(
    <SettingsScreen
      settings={{ ...defaultSettings, ...overrides }}
      setSettings={vi.fn()}
      llmProviders={providers}
      searchProviders={["tavily"]}
      backendStatus="online"
    />
  );
}

describe("SettingsScreen language selector", () => {
  beforeEach(() => {
    changeLanguage.mockClear();
  });

  it("offers all 6 supported languages", async () => {
    const user = userEvent.setup();
    renderSettings();
    // The language selector lives in the 'appearance' section — navigate first.
    await user.click(screen.getByTestId("settings-nav-appearance"));
    await user.click(document.getElementById("settings-language") as HTMLButtonElement);
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(6);
  });

  it("calls i18n.changeLanguage('zh') when Chinese is selected", async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByTestId("settings-nav-appearance"));
    await user.click(document.getElementById("settings-language") as HTMLButtonElement);
    const zhOption = screen
      .getAllByRole("option")
      .find((o) => /简体中文/.test(o.textContent ?? ""));
    expect(zhOption).toBeTruthy();
    await user.click(zhOption as HTMLElement);
    expect(changeLanguage).toHaveBeenCalledWith("zh");
  });
});

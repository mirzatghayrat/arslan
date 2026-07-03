/**
 * SettingsScreen component tests.
 *
 * Strategy: mock `../api/client` so no HTTP calls are made, and mock
 * `react-i18next` so `useTranslation` returns a simple passthrough `t`.
 * The component receives settings/setSettings/llmProviders/searchProviders
 * directly as props.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── i18n mock ──────────────────────────────────────────────────────────────────
// Must be hoisted before imports that use react-i18next.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock ───────────────────────────────────────────────────────────────────
const mockUpdateSettings = vi.fn().mockResolvedValue({});
vi.mock("../api/client", () => ({
  api: {
    updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
  },
  API_BASE: "",
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: vi.fn().mockResolvedValue([]),
  addProviderConfig: vi.fn().mockResolvedValue({}),
  updateProviderConfig: vi.fn().mockResolvedValue({}),
  setPrimaryProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  deleteProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
}));

// ── auth store mock (api/client imports authStore) ─────────────────────────────
vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

import SettingsScreen from "../components/SettingsScreen";
import type { AppSettings } from "../types";
import type { ProviderOption } from "../api/client.types";

const defaultSettings: AppSettings = {
  searchProvider: "tavily",
  apiKeySearch: "tvly-••••",
  githubToken: "",
  language: "en",
  theme: "dark",
  telemetry: false,
  spawnMode: "auto",
  llmStrategy: "single",
  distillOnSessionEnd: true,
  orchestratorShellEnabled: false,
  shellConfirmPolicy: "ask_all",
};

const providers: ProviderOption[] = [
  { key: "anthropic", label: "Anthropic", base_url: "https://api.anthropic.com", default_model: "claude-sonnet-4-5", native: true, models: ["claude-sonnet-4-5"] },
  { key: "openai", label: "OpenAI", base_url: "https://api.openai.com", default_model: "gpt-4o", native: false, models: ["gpt-4o"] },
];

const searchProviders = ["tavily", "serpapi"];

function renderSettings(overrides: Partial<AppSettings> = {}, backendStatus: "online" | "offline" | "checking" = "online") {
  const settings = { ...defaultSettings, ...overrides };
  const setSettings = vi.fn();
  const { rerender } = render(
    <SettingsScreen
      settings={settings}
      setSettings={setSettings}
      llmProviders={providers}
      searchProviders={searchProviders}
      backendStatus={backendStatus}
    />
  );
  return { setSettings, rerender };
}

describe("SettingsScreen", () => {
  beforeEach(() => {
    mockUpdateSettings.mockClear();
  });

  it("renders without crashing", () => {
    renderSettings();
    // The heading is hardcoded text in the component (not translated)
    expect(screen.getByText("System Diagnostics & Configuration")).toBeInTheDocument();
  });

  // ── Legacy LLM fields must be ABSENT ──────────────────────────────────────────

  it("does NOT render the legacy LLM provider dropdown", () => {
    renderSettings();
    expect(document.getElementById("settings-llm-provider")).toBeNull();
  });

  it("does NOT render the legacy LLM model input", () => {
    renderSettings();
    expect(document.getElementById("settings-llm-model")).toBeNull();
  });

  it("does NOT render the legacy LLM API key input", () => {
    renderSettings();
    expect(document.getElementById("settings-llm-key")).toBeNull();
  });

  // ── Multi-config list must be PRESENT ─────────────────────────────────────────

  it("renders the multi-config provider list section heading", () => {
    renderSettings();
    // ProviderConfigList is rendered inside the card whose heading key is 'settings.sectionLlmConfig'
    expect(screen.getByText("settings.sectionLlmConfig")).toBeInTheDocument();
  });

  // ── Kept fields must still be present ─────────────────────────────────────────

  it("renders the search provider dropdown with fetched options", async () => {
    const user = userEvent.setup();
    renderSettings();
    // Custom Select renders a button trigger; open it to inspect options
    const trigger = document.getElementById("settings-search-provider") as HTMLButtonElement;
    expect(trigger).not.toBeNull();
    await user.click(trigger);
    // Options appear as role="option" in the listbox
    const options = screen.getAllByRole("option").map((o) => o.textContent?.trim());
    expect(options.some((o) => /tavily/i.test(o ?? ""))).toBe(true);
    expect(options.some((o) => /serpapi/i.test(o ?? ""))).toBe(true);
  });

  it("renders the search API key input", () => {
    renderSettings();
    expect(document.getElementById("settings-search-key")).not.toBeNull();
  });

  it("renders the language dropdown", () => {
    renderSettings();
    expect(document.getElementById("settings-language")).not.toBeNull();
  });

  it("shows the offline banner when backendStatus is offline", () => {
    renderSettings({}, "offline");
    expect(screen.getByText(/Backend not connected/i)).toBeInTheDocument();
  });

  it("save button is disabled when backend is offline", () => {
    renderSettings({}, "offline");
    const saveBtn = document.getElementById("settings-save-button") as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
  });

  it("save button is enabled when backend is online", () => {
    renderSettings();
    const saveBtn = document.getElementById("settings-save-button") as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(false);
  });

  it("calls api.updateSettings on form submit", async () => {
    const user = userEvent.setup();
    renderSettings();
    const saveBtn = document.getElementById("settings-save-button") as HTMLButtonElement;
    await user.click(saveBtn);
    await waitFor(() => {
      expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    });
  });

  it("does not send empty search key on save", async () => {
    const user = userEvent.setup();
    renderSettings({ apiKeySearch: "" });
    await user.click(document.getElementById("settings-save-button")!);
    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalled());
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.search_api_key).toBeUndefined();
  });
});

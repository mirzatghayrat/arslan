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
}));

// ── auth store mock (api/client imports authStore) ─────────────────────────────
vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

import SettingsScreen from "../components/SettingsScreen";
import type { AppSettings } from "../types";
import type { ProviderOption } from "../api/client.types";

const defaultSettings: AppSettings = {
  llmProvider: "anthropic",
  llmModel: "claude-sonnet-4-5",
  searchProvider: "tavily",
  apiKeyLLM: "sk-ant-••••",
  apiKeySearch: "tvly-••••",
  language: "en",
  theme: "dark",
  telemetry: false,
  spawnMode: "auto",
};

const providers: ProviderOption[] = [
  { key: "anthropic", label: "Anthropic", base_url: "https://api.anthropic.com", default_model: "claude-sonnet-4-5", native: true },
  { key: "openai", label: "OpenAI", base_url: "https://api.openai.com", default_model: "gpt-4o", native: false },
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

  it("renders the LLM provider dropdown with fetched providers", () => {
    renderSettings();
    const select = document.getElementById("settings-llm-provider") as HTMLSelectElement;
    expect(select).not.toBeNull();
    // Both providers should be present as options
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("anthropic");
    expect(options).toContain("openai");
  });

  it("renders the current provider as selected", () => {
    renderSettings({ llmProvider: "openai" });
    const select = document.getElementById("settings-llm-provider") as HTMLSelectElement;
    expect(select.value).toBe("openai");
  });

  it("renders the search provider dropdown with fetched options", () => {
    renderSettings();
    const select = document.getElementById("settings-search-provider") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("tavily");
    expect(options).toContain("serpapi");
  });

  it("shows the current model value in the model input", () => {
    renderSettings({ llmModel: "claude-opus-4" });
    const input = document.getElementById("settings-llm-model") as HTMLInputElement;
    expect(input.value).toBe("claude-opus-4");
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

  it("does not send masked LLM key on save", async () => {
    const user = userEvent.setup();
    renderSettings({ apiKeyLLM: "••••••••" });
    await user.click(document.getElementById("settings-save-button")!);
    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalled());
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.llm_api_key).toBeUndefined();
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

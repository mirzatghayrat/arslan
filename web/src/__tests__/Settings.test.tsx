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
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
    // SettingsScreen renders <EmbeddingSettings/>, which calls api.embeddingStatus()
    // in an effect. Without this the call throws (undefined) → unhandled rejection.
    embeddingStatus: vi.fn().mockResolvedValue(null),
    // SettingsScreen renders <AccessTokenSettings/>, which calls api.getAccessToken().
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
  probeProviderHealth: vi.fn().mockResolvedValue({
    state: "reachable_models", latency_ms: 1, detail: null, last_health_at: "2026-07-12T00:00:00",
  }),
}));

// ── auth store mock (api/client imports authStore) ─────────────────────────────
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
    expect(screen.getByText("settings.pageTitle")).toBeInTheDocument();
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
    // The search controls live in the 'search' section — navigate there first.
    await user.click(screen.getByTestId("settings-nav-search"));
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
    fireEvent.click(screen.getByTestId("settings-nav-search"));
    expect(document.getElementById("settings-search-key")).not.toBeNull();
  });

  it("renders the language dropdown", () => {
    renderSettings();
    fireEvent.click(screen.getByTestId("settings-nav-appearance"));
    expect(document.getElementById("settings-language")).not.toBeNull();
  });

  it("deep-links to a section via the initialSection prop", () => {
    render(
      <SettingsScreen
        settings={defaultSettings}
        setSettings={vi.fn()}
        llmProviders={providers}
        searchProviders={searchProviders}
        backendStatus="online"
        initialSection="memory"
      />
    );
    // The memory section's distill toggle is mounted from first paint…
    expect(document.getElementById("settings-distill-toggle")).not.toBeNull();
    // …while the default 'providers' section is not.
    expect(screen.queryByText("settings.sectionLlmConfig")).toBeNull();
  });

  it("shows the offline banner when backendStatus is offline", () => {
    renderSettings({}, "offline");
    expect(screen.getByText("ledger.empty_backend_offline")).toBeInTheDocument();
  });

  // ── Task 6: the top Save button is GONE (instant auto-save) ───────────────────

  it("no longer renders the top Save button", () => {
    renderSettings();
    expect(document.getElementById("settings-save-button")).toBeNull();
  });

  it("auto-saves a non-key control change with a single PUT (debounced)", async () => {
    const user = userEvent.setup();
    renderSettings();
    // Advanced section hosts the telemetry toggle (a non-key control).
    await user.click(screen.getByTestId("settings-nav-advanced"));
    await user.click(document.getElementById("settings-telemetry-toggle")!);
    await waitFor(() => {
      expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    }, { timeout: 2000 });
  });

  it("does not send empty search key on auto-save", async () => {
    const user = userEvent.setup();
    renderSettings({ apiKeySearch: "" });
    // Trigger a non-key auto-save (search provider) — the empty key must stay out.
    await user.click(screen.getByTestId("settings-nav-advanced"));
    await user.click(document.getElementById("settings-telemetry-toggle")!);
    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalled(), { timeout: 2000 });
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.search_api_key).toBeUndefined();
  });
});

/**
 * MCP server Settings UI (Task 10).
 *
 * Strategy mirrors distill-frontend.test.tsx: mock `../api/client` so no HTTP
 * is made, mock react-i18next to a passthrough `t`, and feed settings/setSettings
 * as props to <SettingsScreen>. Covers:
 *  1. The advanced-section toggle persists mcp_server_enabled=true through the
 *     existing debounced-save path (saveField -> toBackendSettings -> PUT /settings).
 *  2. McpTokenControl's generate button shows the freshly minted token once,
 *     from local component state only (not the auth store — it isn't the app
 *     bearer token).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── i18n mock ──────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock ───────────────────────────────────────────────────────────────────
const mockUpdateSettings = vi.fn(async (b: Record<string, unknown>) => b);
const mockGenerateMcpToken = vi.fn(async () => ({ token: "MCP-TOKEN-XYZ" }));
vi.mock("../api/client", () => ({
  api: {
    updateSettings: (b: Record<string, unknown>) => mockUpdateSettings(b),
    generateMcpToken: () => mockGenerateMcpToken(),
    getSettings: async () => ({}),
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
  shellConfirmPolicy: "ask_all", workspaceDir: "", heartbeatEnabled: false, heartbeatChecklist: "", lanDiscoveryEnabled: false, sshEnabled: false, defaultReadEnabled: true, voiceOutputEnabled: false,
  mcpServerEnabled: false,
};

const providers: ProviderOption[] = [
  { key: "anthropic", label: "Anthropic", base_url: "https://api.anthropic.com", default_model: "claude-sonnet-4-5", native: true, models: ["claude-sonnet-4-5"] },
];

function renderSettings(overrides: Partial<AppSettings> = {}) {
  const settings = { ...defaultSettings, ...overrides };
  const setSettings = vi.fn();
  render(
    <SettingsScreen
      settings={settings}
      setSettings={setSettings}
      llmProviders={providers}
      searchProviders={["tavily"]}
      backendStatus="online"
    />
  );
  return { setSettings };
}

// The toggle moved to Access & Security, beside the token that guards it.
// Assertions unchanged.
describe("MCP server settings", () => {
  beforeEach(() => vi.clearAllMocks());

  it("toggling on auto-saves mcp_server_enabled=true to the PUT path", async () => {
    const user = userEvent.setup();
    renderSettings({ mcpServerEnabled: false });
    await user.click(screen.getByTestId("settings-nav-access"));
    const toggle = document.getElementById("settings-mcp-server-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    await user.click(toggle);
    expect(toggle.checked).toBe(true);
    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalled(), { timeout: 2000 });
    expect(mockUpdateSettings.mock.calls[0][0].mcp_server_enabled).toBe(true);
  });

  it("reflects mcpServerEnabled=true on mount", async () => {
    const user = userEvent.setup();
    renderSettings({ mcpServerEnabled: true });
    await user.click(screen.getByTestId("settings-nav-access"));
    const toggle = document.getElementById("settings-mcp-server-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
  });

  it("generate shows the token once", async () => {
    const user = userEvent.setup();
    renderSettings({ mcpServerEnabled: true });
    await user.click(screen.getByTestId("settings-nav-access"));
    await user.click(screen.getByTestId("mcp-token-generate"));
    await waitFor(() =>
      expect((screen.getByTestId("mcp-token-value") as HTMLInputElement).value).toBe("MCP-TOKEN-XYZ"));
    expect(mockGenerateMcpToken).toHaveBeenCalledOnce();
  });

  it("does not push the generated token into the auth store", async () => {
    const user = userEvent.setup();
    renderSettings({ mcpServerEnabled: true });
    await user.click(screen.getByTestId("settings-nav-access"));
    await user.click(screen.getByTestId("mcp-token-generate"));
    await waitFor(() =>
      expect((screen.getByTestId("mcp-token-value") as HTMLInputElement).value).toBe("MCP-TOKEN-XYZ"));
    const { useAuthStore } = await import("../stores/authStore");
    expect(useAuthStore.getState().token).toBe("");
  });
});

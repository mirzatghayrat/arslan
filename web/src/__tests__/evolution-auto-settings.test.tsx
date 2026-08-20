/**
 * Auto-evolution Settings UI (S4.2-a).
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
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
  shellConfirmPolicy: "ask_all", workspaceDir: "",
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

// The control moved to Automation, not Advanced — the assertions below are
// unchanged, which is the test that the MOVE preserved behaviour rather than
// quietly changing it.
describe("auto-evolution settings", () => {
  beforeEach(() => vi.clearAllMocks());

  it("is OFF on mount when the backend says off", async () => {
    const user = userEvent.setup();
    renderSettings({ evolutionAuto: false });
    await user.click(screen.getByTestId("settings-nav-automation"));
    const toggle = document.getElementById("settings-evolution-auto-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
  });

  it("reflects evolutionAuto=true on mount", async () => {
    // 🔴 The other direction. Without it, "unchecked on mount" is satisfied by a toggle
    // wired to nothing at all — the default is false, so a dead prop looks identical.
    const user = userEvent.setup();
    renderSettings({ evolutionAuto: true });
    await user.click(screen.getByTestId("settings-nav-automation"));
    const toggle = document.getElementById("settings-evolution-auto-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
  });

  it("turning it on sends the STRING \"on\", not a boolean", async () => {
    // The wire type is "on"/"off"; sending `true` would be dropped by the pydantic
    // schema exactly the way embedding_config_id was, and the toggle would appear to
    // work while never persisting.
    const user = userEvent.setup();
    renderSettings({ evolutionAuto: false });
    await user.click(screen.getByTestId("settings-nav-automation"));
    const toggle = document.getElementById("settings-evolution-auto-toggle") as HTMLInputElement;
    await user.click(toggle);
    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalled(), { timeout: 2000 });
    expect(mockUpdateSettings.mock.calls[0][0].evolution_auto).toBe("on");
  });

  it("turning it off sends \"off\"", async () => {
    const user = userEvent.setup();
    renderSettings({ evolutionAuto: true });
    await user.click(screen.getByTestId("settings-nav-automation"));
    await user.click(document.getElementById("settings-evolution-auto-toggle") as HTMLInputElement);
    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalled(), { timeout: 2000 });
    expect(mockUpdateSettings.mock.calls[0][0].evolution_auto).toBe("off");
  });

  it("always shows the spend warning, in both states", async () => {
    // 🔴 Not decoration. It is the only place a user learns that this spends real money
    // with no cap, and the mitigation (a hard limit at the provider) is the only real
    // guard that exists today. Shown regardless of state: someone deciding whether to
    // turn it ON needs it before they click, not after.
    const user = userEvent.setup();
    for (const state of [false, true]) {
      cleanup();
      renderSettings({ evolutionAuto: state });
      await user.click(screen.getByTestId("settings-nav-automation"));
      expect(screen.getByTestId("evolution-auto-warning").textContent)
        .toContain("settings.evolutionAutoSpendWarning");
    }
  });
});

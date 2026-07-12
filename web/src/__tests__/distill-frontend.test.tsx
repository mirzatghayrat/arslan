/**
 * Frontend distillation tests (Task 7 — Settings toggle half).
 *
 * Strategy mirrors Settings.test.tsx: mock `../api/client` so no HTTP is made,
 * mock react-i18next to a passthrough `t`, and feed settings/setSettings as props.
 * Asserts the distill toggle reflects `distillOnSessionEnd` and that toggling +
 * saving routes the new value through the save/PUT path (api.updateSettings).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
const mockUpdateSettings = vi.fn().mockResolvedValue({});
const mockGetPreferences = vi.fn();
const mockDeletePreference = vi.fn();
vi.mock("../api/client", () => ({
  api: {
    updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
    getPreferences: (...args: unknown[]) => mockGetPreferences(...args),
    deletePreference: (...args: unknown[]) => mockDeletePreference(...args),
    getKnowledge: vi.fn().mockResolvedValue([]),
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
import SpawnDetail from "../components/SpawnDetail";
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

describe("distillation Settings toggle", () => {
  beforeEach(() => {
    mockUpdateSettings.mockClear();
  });

  it("renders the distill toggle reflecting distillOnSessionEnd=true", () => {
    renderSettings({ distillOnSessionEnd: true });
    // The distill toggle lives in the 'memory' section — navigate there first.
    fireEvent.click(screen.getByTestId("settings-nav-memory"));
    const toggle = document.getElementById("settings-distill-toggle") as HTMLInputElement;
    expect(toggle).not.toBeNull();
    expect(toggle.checked).toBe(true);
  });

  it("reflects distillOnSessionEnd=false", () => {
    renderSettings({ distillOnSessionEnd: false });
    fireEvent.click(screen.getByTestId("settings-nav-memory"));
    const toggle = document.getElementById("settings-distill-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
  });

  it("toggling off then saving routes distill_on_session_end=false to the PUT path", async () => {
    const user = userEvent.setup();
    renderSettings({ distillOnSessionEnd: true });
    await user.click(screen.getByTestId("settings-nav-memory"));
    const toggle = document.getElementById("settings-distill-toggle") as HTMLInputElement;
    await user.click(toggle);
    expect(toggle.checked).toBe(false);
    await user.click(document.getElementById("settings-save-button")!);
    await waitFor(() => expect(mockUpdateSettings).toHaveBeenCalled());
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.distill_on_session_end).toBe(false);
  });
});

describe("SpawnDetail learned-preferences block", () => {
  beforeEach(() => {
    mockGetPreferences.mockReset();
    mockDeletePreference.mockReset();
  });

  it("lists the spawn's preferences under the learned-prefs heading", async () => {
    mockGetPreferences.mockResolvedValue({ preferences: ["输出更简短", "标注来源"] });
    render(<SpawnDetail spawnId={3} spawnName="小美" onClose={vi.fn()} />);
    expect(await screen.findByText("spawn.learned_prefs")).toBeTruthy();
    expect(await screen.findByText("输出更简短")).toBeTruthy();
    expect(await screen.findByText("标注来源")).toBeTruthy();
    expect(mockGetPreferences).toHaveBeenCalledWith(3);
  });

  it("deleting a preference calls deletePreference(spawnId, fact) and the row disappears", async () => {
    const user = userEvent.setup();
    mockGetPreferences.mockResolvedValue({ preferences: ["输出更简短", "标注来源"] });
    mockDeletePreference.mockResolvedValue({ preferences: ["输出更简短"] });
    render(<SpawnDetail spawnId={3} spawnName="小美" onClose={vi.fn()} />);
    const row = (await screen.findByText("标注来源")).closest("li")!;
    const delBtn = row.querySelector("button")!;
    await user.click(delBtn);
    await waitFor(() => expect(mockDeletePreference).toHaveBeenCalledWith(3, "标注来源"));
    await waitFor(() => expect(screen.queryByText("标注来源")).toBeNull());
    expect(screen.getByText("输出更简短")).toBeTruthy();
  });
});

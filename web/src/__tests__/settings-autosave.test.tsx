/**
 * SettingsScreen auto-save integration (Settings-T6).
 *
 * The top Save button is gone; persistence is instant. This suite pins the two
 * behaviors that matter most:
 *
 *  1. KEY-TYPE fields (search key / GitHub token) persist on BLUR only, never
 *     per-keystroke — the user's hard constraint. Asserted explicitly below.
 *  2. NON-key controls auto-save (debounced) and never PUT per keystroke.
 *  3. Offline: changes don't crash and never hit the network.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

// ── i18n mock ────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock ─────────────────────────────────────────────────────────────────
const mockUpdateSettings = vi.fn().mockResolvedValue({});
vi.mock("../api/client", () => ({
  api: {
    updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
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
  probeProviderHealth: vi.fn().mockResolvedValue({
    state: "reachable_models", latency_ms: 1, detail: null, last_health_at: "2026-07-12T00:00:00",
  }),
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
  apiKeySearch: "",
  githubToken: "",
  language: "en",
  theme: "dark",
  telemetry: false,
  spawnMode: "auto",
  llmStrategy: "single",
  distillOnSessionEnd: true,
  orchestratorShellEnabled: false,
  shellConfirmPolicy: "ask_all",
  mcpServerEnabled: false,
};

const providers: ProviderOption[] = [
  { key: "anthropic", label: "Anthropic", base_url: "https://api.anthropic.com", default_model: "claude-sonnet-4-5", native: true, models: ["claude-sonnet-4-5"] },
];
const searchProviders = ["tavily", "serpapi"];

function renderSettings(overrides: Partial<AppSettings> = {}, backendStatus: "online" | "offline" = "online") {
  const setSettings = vi.fn();
  render(
    <SettingsScreen
      settings={{ ...defaultSettings, ...overrides }}
      setSettings={setSettings}
      llmProviders={providers}
      searchProviders={searchProviders}
      backendStatus={backendStatus}
    />,
  );
  return { setSettings };
}

describe("SettingsScreen auto-save (Task 6)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockUpdateSettings.mockClear();
    mockUpdateSettings.mockResolvedValue({});
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("removes the top Save button entirely", () => {
    renderSettings();
    expect(document.getElementById("settings-save-button")).toBeNull();
  });

  // ── THE constraint: key fields save on BLUR only, never per-keystroke ─────────
  it("does NOT PUT while typing in the search key, and PUTs exactly once on blur", () => {
    renderSettings();
    fireEvent.click(screen.getByTestId("settings-nav-search"));
    const input = document.getElementById("settings-search-key") as HTMLInputElement;

    // Typing — display updates, but NO save is triggered…
    fireEvent.change(input, { target: { value: "t" } });
    fireEvent.change(input, { target: { value: "tv" } });
    fireEvent.change(input, { target: { value: "tvly-secret" } });
    // …even after any debounce window would have elapsed.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled();

    // Blur commits it — exactly one immediate PUT carrying the key.
    fireEvent.blur(input);
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings.mock.calls[0][0].search_api_key).toBe("tvly-secret");
  });

  it("does NOT PUT when a key field is focused and blurred without editing (dirty-guard)", () => {
    renderSettings({ apiKeySearch: "tv...bcde" }); // pre-filled masked echo
    fireEvent.click(screen.getByTestId("settings-nav-search"));
    const input = document.getElementById("settings-search-key") as HTMLInputElement;
    // Tab through: focus then blur, no change event.
    fireEvent.focus(input);
    fireEvent.blur(input);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled();
  });

  it("saves the GitHub token on blur only", () => {
    renderSettings();
    fireEvent.click(screen.getByTestId("settings-nav-search"));
    const input = document.getElementById("settings-github-token") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ghp_abc" } });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings.mock.calls[0][0].github_token).toBe("ghp_abc");
  });

  it("debounces a non-key toggle into a single PUT (no per-event PUT)", () => {
    renderSettings();
    fireEvent.click(screen.getByTestId("settings-nav-advanced"));
    const toggle = document.getElementById("settings-telemetry-toggle") as HTMLInputElement;
    fireEvent.click(toggle);
    // Nothing before the debounce elapses…
    expect(mockUpdateSettings).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
  });

  it("does not carry a mid-typed (un-blurred) search key on a non-key debounced save", () => {
    renderSettings();
    // Type a real key but do NOT blur it.
    fireEvent.click(screen.getByTestId("settings-nav-search"));
    const keyInput = document.getElementById("settings-search-key") as HTMLInputElement;
    fireEvent.change(keyInput, { target: { value: "tvly-not-blurred" } });
    // Now toggle a non-key control and let its debounce fire.
    fireEvent.click(screen.getByTestId("settings-nav-advanced"));
    fireEvent.click(document.getElementById("settings-telemetry-toggle")!);
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings.mock.calls[0][0].search_api_key).toBeUndefined();
  });

  // ── FIX 2: a background save resolving mid-edit must not revert the typed key
  // to its mask (the sync effect skips key fields the user is editing) ──────────
  it("keeps a key the user is typing when a background non-key save resolves", async () => {
    let resolveTelemetry!: (v: unknown) => void;
    mockUpdateSettings.mockImplementationOnce(
      () => new Promise((res) => { resolveTelemetry = res; }),
    );
    renderSettings({ apiKeySearch: "tv...bcde" }); // pre-filled masked echo

    // Toggle telemetry (non-key) and let its debounced PUT fire and hang.
    fireEvent.click(screen.getByTestId("settings-nav-advanced"));
    fireEvent.click(document.getElementById("settings-telemetry-toggle")!);
    act(() => {
      vi.advanceTimersByTime(600);
    });

    // While that PUT is in flight, the user types a real key.
    fireEvent.click(screen.getByTestId("settings-nav-search"));
    const keyInput = document.getElementById("settings-search-key") as HTMLInputElement;
    fireEvent.change(keyInput, { target: { value: "tvly-typed" } });

    // The background save resolves → onPersisted → parent settings sync fires.
    await act(async () => {
      resolveTelemetry({});
      await Promise.resolve();
    });

    // The typed value survives — NOT reverted to the mask by the sync effect.
    expect((document.getElementById("settings-search-key") as HTMLInputElement).value).toBe("tvly-typed");
  });

  it("does not PUT when the backend is offline (no crash)", () => {
    renderSettings({}, "offline");
    fireEvent.click(screen.getByTestId("settings-nav-advanced"));
    fireEvent.click(document.getElementById("settings-telemetry-toggle")!);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled();
  });

  // ── FIX 3: an offline edit is buffered and flushed once on reconnect ─────────
  it("flushes a buffered offline edit when the backend reconnects", async () => {
    const setSettings = vi.fn();
    const settingsObj = { ...defaultSettings }; // stable identity across rerenders
    const el = (backendStatus: "online" | "offline") => (
      <SettingsScreen
        settings={settingsObj}
        setSettings={setSettings}
        llmProviders={providers}
        searchProviders={searchProviders}
        backendStatus={backendStatus}
      />
    );
    const { rerender } = render(el("offline"));

    fireEvent.click(screen.getByTestId("settings-nav-advanced"));
    fireEvent.click(document.getElementById("settings-shell-toggle")!);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled(); // offline: buffered

    // Backend comes back → reconnect effect flushes the buffer once.
    await act(async () => {
      rerender(el("online"));
      await Promise.resolve();
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings.mock.calls[0][0].orchestrator_shell_enabled).toBe("true");
  });
});

/**
 * Settings regression (fix/provider-key-input) — the SAVED-config API-key field
 * and the "+ Add model" draft's error surfacing.
 *
 * Reproduce-first pins for a settings-redesign regression that blocks new users
 * from setting an API key:
 *   1. An undecryptable saved key (ARSLAN_SECRET_KEY changed) must show an HONEST
 *      reason — not a misleading "requires API key" / generic "API Key" prompt.
 *   2. The saved-config key input must be a FRESH-ENTRY field (decoupled from the
 *      masked server value) that commits the NEW typed value on blur.
 *   3. A rejected addProviderConfig POST must SURFACE the error (draft stays open),
 *      and the happy path must still add + close the draft.
 */

import React, { useState } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── i18n mock (t returns the key verbatim) ──────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock ────────────────────────────────────────────────────────────────────
const mockAddProviderConfig = vi.fn();
const mockUpdateProviderConfig = vi.fn();
const mockFetchProviderModels = vi.fn().mockResolvedValue({
  models: [], fetched_at: null, stale: false, error: null, source: "static",
});
const mockProbeProviderHealth = vi.fn().mockResolvedValue({
  state: "reachable_models", latency_ms: 1, detail: null, last_health_at: "2026-07-12T00:00:00",
});

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
    getAccessToken: vi.fn().mockResolvedValue({ token_required: false, token: null }),
  },
  API_BASE: "",
  addProviderConfig: (...args: unknown[]) => mockAddProviderConfig(...args),
  updateProviderConfig: (...args: unknown[]) => mockUpdateProviderConfig(...args),
  setPrimaryProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  deleteProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  fetchProviderModels: (...args: unknown[]) => mockFetchProviderModels(...args),
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: vi.fn().mockResolvedValue([]),
  testLlm: vi.fn().mockResolvedValue({ ok: true }),
  testProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
  probeProviderHealth: (...args: unknown[]) => mockProbeProviderHealth(...args),
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: Object.assign(
    (sel: (s: { token: string; setToken: (t: string) => void }) => unknown) =>
      sel({ token: "", setToken: () => {} }),
    { getState: () => ({ token: "", setToken: () => {} }) },
  ),
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderOption, ProviderConfig } from "../api/client.types";

const providers: ProviderOption[] = [
  { key: "deepseek", label: "DeepSeek", base_url: "", default_model: "deepseek-chat", native: false, models: ["deepseek-chat", "deepseek-reasoner"] },
];

beforeEach(() => {
  mockAddProviderConfig.mockReset();
  mockUpdateProviderConfig.mockReset().mockResolvedValue({});
  mockFetchProviderModels.mockClear();
  mockProbeProviderHealth.mockClear();
});

describe("saved-config API-key field", () => {
  it("undecryptable key shows the honest reason, not the generic requires-key prompt", () => {
    const configs: ProviderConfig[] = [
      // Backend masks an undecryptable key to "" and flags key_status.
      { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "", key_status: "undecryptable", is_primary: true },
    ];
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    // Honest inline reason is visible and names the real cause (ARSLAN_SECRET_KEY).
    const reason = screen.getByTestId("provider-config-key-undecryptable-0");
    expect(reason).toBeInTheDocument();
    expect(reason.textContent).toContain("settings.keyUndecryptableReason");
    // The input prompts a re-entry, NOT the generic "API Key" placeholder that
    // falsely reads as "requires API key".
    const key = screen.getByTestId("provider-config-key-0") as HTMLInputElement;
    expect(key.placeholder).toBe("settings.keyReenter");
    expect(key.placeholder).not.toBe("settings.labelConfigApiKey");
  });

  it("is a fresh-entry field: commits the NEW typed value on blur (not the mask)", async () => {
    const configs: ProviderConfig[] = [
      { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "de...cd", key_status: "set", is_primary: true },
    ];
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    const key = screen.getByTestId("provider-config-key-0") as HTMLInputElement;
    // Decoupled from the masked server value — starts empty, prompts a replace.
    expect(key.value).toBe("");
    expect(key.placeholder).toBe("settings.keySavedReplace");

    fireEvent.change(key, { target: { value: "sk-brand-new" } });
    fireEvent.blur(key);

    await waitFor(() => expect(mockUpdateProviderConfig).toHaveBeenCalled());
    const [id, patch] = mockUpdateProviderConfig.mock.calls[0];
    expect(id).toBe(1);
    expect(patch.api_key).toBe("sk-brand-new");
    // NEVER re-persist the mask.
    expect(patch.api_key).not.toBe("de...cd");
    // Draft clears after commit so the field is ready for the next replace.
    expect((screen.getByTestId("provider-config-key-0") as HTMLInputElement).value).toBe("");
  });

  it("empty blur does not commit anything (keeps the stored key)", async () => {
    const configs: ProviderConfig[] = [
      { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "de...cd", key_status: "set", is_primary: true },
    ];
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={configs} onConfigsChange={vi.fn()} />,
    );
    const key = screen.getByTestId("provider-config-key-0") as HTMLInputElement;
    fireEvent.focus(key);
    fireEvent.blur(key);
    await Promise.resolve();
    expect(mockUpdateProviderConfig).not.toHaveBeenCalled();
  });
});

describe("add-draft error surfacing", () => {
  it("surfaces a rejected addProviderConfig and keeps the draft open", async () => {
    const user = userEvent.setup();
    mockAddProviderConfig.mockRejectedValueOnce(new Error("server said no"));
    render(
      <ProviderConfigList llmProviders={providers} providerConfigs={[]} onConfigsChange={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));
    expect(screen.getByTestId("provider-draft-model")).toBeInTheDocument();
    await user.click(screen.getByTestId("provider-draft-confirm"));
    // Error is visible and carries the backend message; draft is NOT dismissed.
    const err = await screen.findByTestId("provider-draft-error");
    expect(err.textContent).toContain("server said no");
    expect(screen.getByTestId("provider-draft-model")).toBeInTheDocument();
  });

  it("happy path still adds and closes the draft", async () => {
    const user = userEvent.setup();
    mockAddProviderConfig.mockResolvedValueOnce({
      id: 3, label: "C", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "", key_status: "unset", is_primary: false,
    });
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>([]);
      return (
        <ProviderConfigList llmProviders={providers} providerConfigs={cfgs} onConfigsChange={setCfgs} />
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));
    await user.click(screen.getByTestId("provider-draft-confirm"));
    await waitFor(() => expect(mockAddProviderConfig).toHaveBeenCalled());
    // Draft closed, no error line, the new config's master row landed.
    await waitFor(() => expect(screen.queryByTestId("provider-draft-model")).toBeNull());
    expect(screen.queryByTestId("provider-draft-error")).toBeNull();
    expect(screen.getByTestId("provider-master-row-0")).toBeInTheDocument();
  });
});

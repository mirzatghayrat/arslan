/**
 * Task A9 — Settings multi-config list + strategy dropdown.
 *
 * Tests the ProviderConfigList presentational child component extracted from
 * SettingsScreen. This keeps the test clean and the component focused.
 */

import React, { useState } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── i18n mock ──────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock (ProviderConfigList calls client functions directly) ───────────────
const mockAddProviderConfig = vi.fn().mockResolvedValue({ id: 3, label: "C", provider: "deepseek", model: "deepseek-reasoner", base_url: "", api_key: "", is_primary: false });
const mockUpdateProviderConfig = vi.fn().mockResolvedValue({});
const mockSetPrimaryProviderConfig = vi.fn().mockResolvedValue({ ok: true });
const mockDeleteProviderConfig = vi.fn().mockResolvedValue({ ok: true });
const mockFetchProviderModels = vi.fn().mockResolvedValue({
  models: [],
  fetched_at: null,
  stale: false,
  error: null,
  source: "static",
});

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
    getAccessToken: vi.fn().mockResolvedValue({ token_required: false, token: null }),
    resetAccessToken: vi.fn().mockResolvedValue({ token: "new-token" }),
  },
  API_BASE: "",
  addProviderConfig: (...args: unknown[]) => mockAddProviderConfig(...args),
  updateProviderConfig: (...args: unknown[]) => mockUpdateProviderConfig(...args),
  setPrimaryProviderConfig: (...args: unknown[]) => mockSetPrimaryProviderConfig(...args),
  deleteProviderConfig: (...args: unknown[]) => mockDeleteProviderConfig(...args),
  fetchProviderModels: (...args: unknown[]) => mockFetchProviderModels(...args),
  suggestPrimary: vi.fn().mockResolvedValue(null),
  getCatalog: vi.fn().mockResolvedValue([]),
  testLlm: vi.fn().mockResolvedValue({ ok: true }),
  testProviderConfig: vi.fn().mockResolvedValue({ ok: true }),
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
  { key: "qwen", label: "Qwen", base_url: "", default_model: "qwen-max", native: false, models: ["qwen-max", "qwen-plus"] },
];

const configs: ProviderConfig[] = [
  { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "de...cd", is_primary: true },
  { id: 2, label: "B", provider: "qwen", model: "qwen-max", base_url: "", api_key: "qw...ef", is_primary: false },
];

describe("ProviderConfigList", () => {
  it("renders configured rows with provider model visible", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Model comboboxes: free-text inputs showing the stored model id
    const model0 = screen.getByTestId("provider-config-model-0") as HTMLInputElement;
    expect(model0.value).toBe("deepseek-chat");
    const model1 = screen.getByTestId("provider-config-model-1") as HTMLInputElement;
    expect(model1.value).toBe("qwen-max");
  });

  it("shows a set-primary button for non-primary rows", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // At least one "Set primary" control for the non-primary row
    expect(screen.getAllByRole("button", { name: /primary/i }).length).toBeGreaterThan(0);
  });

  it("marks the primary row with a star indicator", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // The primary row should show a ★ character
    expect(screen.getByText("★")).toBeInTheDocument();
  });

  it("shows an Add model button", () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // The i18n mock returns the key; the key ends with "btnAddModel"
    expect(screen.getByRole("button", { name: /btnAddModel/i })).toBeInTheDocument();
  });

  it("calls setPrimaryProviderConfig when set-primary is clicked", async () => {
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    const setPrimaryBtns = screen.getAllByRole("button", { name: /primary/i });
    fireEvent.click(setPrimaryBtns[0]);
    // Wait a tick for async
    await new Promise((r) => setTimeout(r, 0));
    expect(mockSetPrimaryProviderConfig).toHaveBeenCalledWith(2);
  });

  it("renders model options from the selected provider's models array", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Focus the model combobox for the first (deepseek) row → dropdown opens
    const model0 = screen.getByTestId("provider-config-model-0");
    await user.click(model0);
    // Both static seed models should be suggested (dynamic mock returns [])
    await waitFor(() => {
      const options = screen.getAllByRole("option").map((o) => o.textContent ?? "");
      expect(options.some((t) => t.includes("deepseek-chat"))).toBe(true);
      expect(options.some((t) => t.includes("deepseek-reasoner"))).toBe(true);
    });
    // First focus lazily fetched the dynamic model list for that row
    expect(mockFetchProviderModels).toHaveBeenCalledWith(1, false);
  });

  it("renders a strategy dropdown with 4 options", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );
    // Custom Select: trigger is a button with id "provider-strategy-select"
    const strategyTrigger = document.getElementById("provider-strategy-select") as HTMLButtonElement;
    await user.click(strategyTrigger);
    // All 4 strategy options should appear in the listbox
    const options = screen.getAllByRole("option").map((o) => o.getAttribute("data-value") ?? o.textContent?.trim());
    // Check via text content matching i18n key
    const optionTexts = screen.getAllByRole("option").map((o) => o.textContent?.trim());
    expect(optionTexts.some((t) => /single/i.test(t ?? ""))).toBe(true);
    expect(optionTexts.some((t) => /cost/i.test(t ?? ""))).toBe(true);
    expect(optionTexts.some((t) => /balanced/i.test(t ?? ""))).toBe(true);
    expect(optionTexts.some((t) => /performance/i.test(t ?? ""))).toBe(true);
  });

  it("calls onStrategyChange when strategy option is clicked", async () => {
    const user = userEvent.setup();
    const onStrategyChange = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={onStrategyChange}
      />
    );
    // Open the strategy custom select
    const strategyTrigger = document.getElementById("provider-strategy-select") as HTMLButtonElement;
    await user.click(strategyTrigger);
    // Click "balanced" option (2 configs so not disabled)
    const balancedOpt = screen.getAllByRole("option").find((o) =>
      /balanced/i.test(o.textContent ?? ""),
    );
    expect(balancedOpt).toBeTruthy();
    await user.click(balancedOpt!);
    expect(onStrategyChange).toHaveBeenCalledWith("balanced");
  });
});

// ── Change 1: base_url is updated when a saved row's provider changes ─────────

describe("base_url update on provider change (Change 1)", () => {
  it("switching a saved row's provider sends the new provider's base_url in the update patch", async () => {
    const user = userEvent.setup();

    // Use providers with distinct base_urls
    const providersWithUrls: ProviderOption[] = [
      {
        key: "deepseek",
        label: "DeepSeek",
        base_url: "https://api.deepseek.com",
        default_model: "deepseek-chat",
        native: false,
        models: ["deepseek-chat"],
      },
      {
        key: "gemini",
        label: "Gemini",
        base_url: "",
        default_model: "gemini-1.5-flash",
        native: true,
        models: ["gemini-1.5-flash"],
      },
    ];

    const oneConfig: ProviderConfig[] = [
      {
        id: 10,
        label: "X",
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
        api_key: "ds-key",
        is_primary: true,
      },
    ];

    mockUpdateProviderConfig.mockResolvedValue({});

    render(
      <ProviderConfigList
        llmProviders={providersWithUrls}
        providerConfigs={oneConfig}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    // Open provider select for row 0 and switch to Gemini
    const providerTrigger = document.getElementById("provider-config-provider-0") as HTMLButtonElement;
    expect(providerTrigger).not.toBeNull();
    await user.click(providerTrigger);

    const geminiOption = screen.getAllByRole("option").find((o) =>
      /gemini/i.test(o.textContent ?? ""),
    );
    expect(geminiOption).toBeTruthy();
    await user.click(geminiOption!);

    // The updateProviderConfig call should include base_url matching Gemini's base_url ("")
    await waitFor(() => {
      expect(mockUpdateProviderConfig).toHaveBeenCalledWith(
        10,
        expect.objectContaining({ base_url: "" }),
      );
    });
  });
});

// ── Provider P2: dynamic model list + base_url blur-save + ollama hint ────────

describe("dynamic model list integration (Provider P2)", () => {
  it("base_url input saves on blur only, never per keystroke", async () => {
    mockUpdateProviderConfig.mockClear();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={vi.fn()}
      />
    );
    // deepseek is non-native → base_url input rendered for row 0
    const baseUrl0 = screen.getByTestId("provider-config-baseurl-0") as HTMLInputElement;
    fireEvent.change(baseUrl0, { target: { value: "https://my-proxy.example/v1" } });
    // No network write while typing
    expect(mockUpdateProviderConfig).not.toHaveBeenCalled();
    fireEvent.blur(baseUrl0, { target: { value: "https://my-proxy.example/v1" } });
    await waitFor(() => {
      expect(mockUpdateProviderConfig).toHaveBeenCalledWith(1, {
        base_url: "https://my-proxy.example/v1",
      });
    });
    // Blur without an edit must not fire another save
    mockUpdateProviderConfig.mockClear();
    fireEvent.blur(baseUrl0, { target: { value: "https://my-proxy.example/v1" } });
    await new Promise((r) => setTimeout(r, 0));
    expect(mockUpdateProviderConfig).not.toHaveBeenCalled();
  });

  it("refresh button re-fetches the row's dynamic model list", async () => {
    const user = userEvent.setup();
    mockFetchProviderModels.mockClear();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={vi.fn()}
      />
    );
    const refreshBtns = screen.getAllByRole("button", { name: "settings.modelRefresh" });
    await user.click(refreshBtns[0]);
    await waitFor(() => {
      expect(mockFetchProviderModels).toHaveBeenCalledWith(1, true);
    });
  });

  it("shows stale + ollama-not-detected hints when the daemon is down", async () => {
    const user = userEvent.setup();
    mockFetchProviderModels.mockClear();
    mockFetchProviderModels.mockResolvedValueOnce({
      models: [],
      fetched_at: null,
      stale: true,
      error: "connection refused",
      source: "static",
    });
    const ollamaProviders: ProviderOption[] = [
      { key: "ollama", label: "Ollama", base_url: "http://127.0.0.1:11434", default_model: "", native: false, models: [] },
    ];
    const ollamaConfigs: ProviderConfig[] = [
      { id: 7, label: "O", provider: "ollama", model: "llama3", base_url: "http://127.0.0.1:11434", api_key: "x", is_primary: true },
    ];
    render(
      <ProviderConfigList
        llmProviders={ollamaProviders}
        providerConfigs={ollamaConfigs}
        onConfigsChange={vi.fn()}
      />
    );
    // First focus triggers the lazy fetch which returns the daemon-down result
    await user.click(screen.getByTestId("provider-config-model-0"));
    await waitFor(() => {
      // stale + fetched_at null → pure static-fallback hint
      expect(screen.getByText("settings.modelStaticFallback")).toBeInTheDocument();
      // ollama empty list + error → not-detected hint with download link
      const hint = screen.getByTestId("provider-config-ollama-hint-0");
      expect(hint.textContent).toContain("settings.ollamaNotDetected");
      const link = hint.querySelector("a") as HTMLAnchorElement;
      expect(link.href).toBe("https://ollama.com/download");
      expect(link.target).toBe("_blank");
      expect(link.rel).toBe("noreferrer");
    });
  });

  it("saving a draft fires a refresh fetch for the new config id", async () => {
    const user = userEvent.setup();
    mockFetchProviderModels.mockClear();
    mockAddProviderConfig.mockClear();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));
    const keyInput = screen.getByPlaceholderText("settings.labelConfigApiKey");
    fireEvent.change(keyInput, { target: { value: "sk-test" } });
    await user.click(screen.getByTestId("provider-draft-confirm"));
    await waitFor(() => {
      // fetch-on-key-save doubles as key validation (refresh=true, new id=3)
      expect(mockFetchProviderModels).toHaveBeenCalledWith(3, true);
    });
  });

  it("switching a row's provider invalidates its cached dynamic model list (FIX A)", async () => {
    const user = userEvent.setup();
    mockFetchProviderModels.mockClear();
    mockUpdateProviderConfig.mockClear();
    // First fetch returns a deepseek-only dynamic list
    mockFetchProviderModels.mockResolvedValueOnce({
      models: [
        { id: "dyn-deepseek-model", display_name: null, context_window: null, capabilities: [], source: "api" },
      ],
      fetched_at: "2026-07-12T00:00:00",
      stale: false,
      error: null,
      source: "api",
    });

    // Stateful harness so provider switches actually re-render the row
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>([
        { id: 1, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "k", is_primary: true },
      ]);
      return (
        <ProviderConfigList
          llmProviders={providers}
          providerConfigs={cfgs}
          onConfigsChange={setCfgs}
        />
      );
    }
    render(<Harness />);

    // First focus loads the deepseek dynamic list
    await user.click(screen.getByTestId("provider-config-model-0"));
    await waitFor(() => {
      const opts = screen.getAllByRole("option").map((o) => o.textContent ?? "");
      expect(opts.some((t) => t.includes("dyn-deepseek-model"))).toBe(true);
    });
    expect(mockFetchProviderModels).toHaveBeenCalledTimes(1);

    // Switch the row's provider to qwen
    await user.click(document.getElementById("provider-config-provider-0") as HTMLButtonElement);
    const qwenOpt = screen.getAllByRole("option").find((o) => /qwen/i.test(o.textContent ?? ""));
    expect(qwenOpt).toBeTruthy();
    await user.click(qwenOpt!);
    await waitFor(() => {
      expect(
        (screen.getByTestId("provider-config-model-0") as HTMLInputElement).value,
      ).toBe("qwen-max");
    });

    // Re-focus: the deepseek cache must be gone → refetch fires and the
    // suggestions are the NEW provider's seed models
    await user.click(screen.getByTestId("provider-config-model-0"));
    await waitFor(() => {
      expect(mockFetchProviderModels).toHaveBeenCalledTimes(2);
    });
    expect(mockFetchProviderModels).toHaveBeenLastCalledWith(1, false);
    const opts = screen.getAllByRole("option").map((o) => o.textContent ?? "");
    expect(opts.some((t) => t.includes("qwen-max"))).toBe(true);
    expect(opts.some((t) => t.includes("dyn-deepseek-model"))).toBe(false);
  });

  it("failed base_url blur-save retries on the next blur (FIX D)", async () => {
    mockUpdateProviderConfig.mockClear();
    mockUpdateProviderConfig.mockRejectedValueOnce(new Error("boom"));
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={vi.fn()}
      />
    );
    const baseUrl0 = screen.getByTestId("provider-config-baseurl-0") as HTMLInputElement;
    fireEvent.change(baseUrl0, { target: { value: "https://retry.example/v1" } });
    fireEvent.blur(baseUrl0, { target: { value: "https://retry.example/v1" } });
    await waitFor(() => expect(mockUpdateProviderConfig).toHaveBeenCalledTimes(1));
    // The write failed — the next blur must retry instead of silently dropping it
    fireEvent.blur(baseUrl0, { target: { value: "https://retry.example/v1" } });
    await waitFor(() => expect(mockUpdateProviderConfig).toHaveBeenCalledTimes(2));
    expect(mockUpdateProviderConfig).toHaveBeenLastCalledWith(1, {
      base_url: "https://retry.example/v1",
    });
  });
});

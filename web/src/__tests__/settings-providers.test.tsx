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
const mockTestProviderConfig = vi.fn().mockResolvedValue({ ok: true });
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
  testProviderConfig: (...args: unknown[]) => mockTestProviderConfig(...args),
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
  it("renders configured rows with provider model visible", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Master list shows every config's model id as small text
    expect(screen.getByText("deepseek-chat")).toBeInTheDocument();
    expect(screen.getByText("qwen-max")).toBeInTheDocument();
    // Row 0 (primary) is selected by default → its detail combobox shows its model
    const model0 = screen.getByTestId("provider-config-model-0") as HTMLInputElement;
    expect(model0.value).toBe("deepseek-chat");
    // Selecting row 1 swaps the detail pane to that config's fields
    await user.click(screen.getByTestId("provider-card-row-1"));
    const model1 = screen.getByTestId("provider-config-model-1") as HTMLInputElement;
    expect(model1.value).toBe("qwen-max");
  });

  it("shows a set-primary button for the selected non-primary row", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Primary row is selected by default → no set-primary button in the detail
    expect(screen.queryByRole("button", { name: /btnSetPrimary/i })).toBeNull();
    // Selecting the non-primary row reveals its "Set primary" control
    await user.click(screen.getByTestId("provider-card-row-1"));
    // Set-primary moved behind the overflow: it is rare, and the row should be
    // dominated by the one button anyone presses (Test).
    await user.click(screen.getByTestId("provider-config-more-1"));
    expect(screen.getByTestId("provider-config-primary-1")).toBeInTheDocument();
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
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={configs}
        onConfigsChange={onUpdate}
      />
    );
    // Select the non-primary row, then click its detail "Set primary" button
    await user.click(screen.getByTestId("provider-card-row-1"));
    await user.click(screen.getByTestId("provider-config-more-1"));
    fireEvent.click(screen.getByTestId("provider-config-primary-1"));
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

  it("custom draft save stays disabled until base_url is filled (P3)", async () => {
    const user = userEvent.setup();
    mockAddProviderConfig.mockClear();
    // custom first → openDraft starts on the custom provider
    const customFirst: ProviderOption[] = [
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
      ...providers,
    ];
    render(
      <ProviderConfigList
        llmProviders={customFirst}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));

    // Fill model (combobox commits on blur) and api_key — base_url still blank
    const modelInput = screen.getByTestId("provider-draft-model");
    fireEvent.change(modelInput, { target: { value: "my-model" } });
    fireEvent.blur(modelInput);
    const keyInput = screen.getByPlaceholderText("settings.labelConfigApiKey");
    fireEvent.change(keyInput, { target: { value: "sk-test" } });

    const confirm = screen.getByTestId("provider-draft-confirm") as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    // The required-base_url hint shows while blank
    expect(screen.getByTestId("provider-draft-custom-required")).toBeInTheDocument();

    // Fill base_url → save enabled, hint gone
    fireEvent.change(screen.getByTestId("provider-draft-baseurl"), {
      target: { value: "http://localhost:1234/v1" },
    });
    expect((screen.getByTestId("provider-draft-confirm") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("provider-draft-custom-required")).toBeNull();

    await user.click(screen.getByTestId("provider-draft-confirm"));
    await waitFor(() => {
      expect(mockAddProviderConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "custom",
          model: "my-model",
          base_url: "http://localhost:1234/v1",
        }),
      );
    });
  });

  it("quick-pick chip fills the draft base_url field (P3)", async () => {
    const user = userEvent.setup();
    const customFirst: ProviderOption[] = [
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
      ...providers,
    ];
    render(
      <ProviderConfigList
        llmProviders={customFirst}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));

    // Chips render for the custom draft; clicking LM Studio fills the input
    await user.click(screen.getByRole("button", { name: "LM Studio" }));
    expect(
      (screen.getByTestId("provider-draft-baseurl") as HTMLInputElement).value,
    ).toBe("http://localhost:1234/v1");
    // Another chip overwrites it
    await user.click(screen.getByRole("button", { name: "vLLM" }));
    expect(
      (screen.getByTestId("provider-draft-baseurl") as HTMLInputElement).value,
    ).toBe("http://localhost:8000/v1");
  });

  it("quick-pick chip on a saved row fills + focuses WITHOUT persisting; natural blur persists (FIX 3)", async () => {
    const user = userEvent.setup();
    mockUpdateProviderConfig.mockClear();
    const customProviders: ProviderOption[] = [
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
    ];
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>([
        { id: 5, label: "C", provider: "custom", model: "my-model", base_url: "", api_key: "", is_primary: true },
      ]);
      return (
        <ProviderConfigList
          llmProviders={customProviders}
          providerConfigs={cfgs}
          onConfigsChange={setCfgs}
        />
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "llama.cpp" }));
    const baseUrl0 = screen.getByTestId("provider-config-baseurl-0") as HTMLInputElement;
    // Chip fills the input and focuses it for review — persistence must wait
    // for a NATURAL blur (the Ollama chip is a placeholder the user must edit).
    expect(baseUrl0.value).toBe("http://localhost:8080/v1");
    expect(document.activeElement).toBe(baseUrl0);
    expect(mockUpdateProviderConfig).not.toHaveBeenCalled();
    fireEvent.blur(baseUrl0, { target: { value: "http://localhost:8080/v1" } });
    await waitFor(() => {
      expect(mockUpdateProviderConfig).toHaveBeenCalledWith(5, {
        base_url: "http://localhost:8080/v1",
      });
    });
    expect(mockUpdateProviderConfig).toHaveBeenCalledTimes(1);
  });

  it("keyless ollama draft saves (FIX 1)", async () => {
    const user = userEvent.setup();
    mockAddProviderConfig.mockClear();
    const ollamaFirst: ProviderOption[] = [
      { key: "ollama", label: "Ollama", base_url: "http://localhost:11434/v1", default_model: "", native: false, models: [] },
    ];
    render(
      <ProviderConfigList
        llmProviders={ollamaFirst}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));
    // Fill only the model — api_key stays empty (local daemon needs none)
    const modelInput = screen.getByTestId("provider-draft-model");
    fireEvent.change(modelInput, { target: { value: "llama3" } });
    fireEvent.blur(modelInput);
    const confirm = screen.getByTestId("provider-draft-confirm") as HTMLButtonElement;
    expect(confirm.disabled).toBe(false);
    await user.click(confirm);
    await waitFor(() => {
      expect(mockAddProviderConfig).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "ollama", model: "llama3", api_key: "" }),
      );
    });
  });

  it("keyless custom draft with base_url saves (FIX 1)", async () => {
    const user = userEvent.setup();
    mockAddProviderConfig.mockClear();
    const customFirst: ProviderOption[] = [
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
    ];
    render(
      <ProviderConfigList
        llmProviders={customFirst}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: /btnAddModel/i }));
    const modelInput = screen.getByTestId("provider-draft-model");
    fireEvent.change(modelInput, { target: { value: "my-model" } });
    fireEvent.blur(modelInput);
    fireEvent.change(screen.getByTestId("provider-draft-baseurl"), {
      target: { value: "http://localhost:1234/v1" },
    });
    // api_key left empty — must not gate the save
    const confirm = screen.getByTestId("provider-draft-confirm") as HTMLButtonElement;
    expect(confirm.disabled).toBe(false);
    await user.click(confirm);
    await waitFor(() => {
      expect(mockAddProviderConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "custom",
          model: "my-model",
          base_url: "http://localhost:1234/v1",
          api_key: "",
        }),
      );
    });
  });

  it("switching a saved row to custom is local-pending with hint; base_url blur persists the full patch (FIX 2)", async () => {
    const user = userEvent.setup();
    mockUpdateProviderConfig.mockClear();
    const providersWithCustom: ProviderOption[] = [
      { key: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", default_model: "deepseek-chat", native: false, models: ["deepseek-chat"] },
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
    ];
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>([
        { id: 21, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "https://api.deepseek.com", api_key: "k", is_primary: true },
      ]);
      return (
        <ProviderConfigList
          llmProviders={providersWithCustom}
          providerConfigs={cfgs}
          onConfigsChange={setCfgs}
        />
      );
    }
    render(<Harness />);

    // Switch the row's provider to custom
    await user.click(document.getElementById("provider-config-provider-0") as HTMLButtonElement);
    const customOpt = screen.getAllByRole("option").find((o) => /自定义/.test(o.textContent ?? ""));
    expect(customOpt).toBeTruthy();
    await user.click(customOpt!);

    // NOT silent: switch applied locally, required-base_url hint shows, NO PUT
    // (a PUT with blank base_url would deterministically 422)
    await waitFor(() => {
      expect(screen.getByTestId("provider-config-custom-required-0")).toBeInTheDocument();
    });
    expect(mockUpdateProviderConfig).not.toHaveBeenCalled();

    // Filling base_url and blurring persists provider+model+base_url in ONE PUT
    const baseUrl0 = screen.getByTestId("provider-config-baseurl-0") as HTMLInputElement;
    fireEvent.change(baseUrl0, { target: { value: "http://localhost:1234/v1" } });
    fireEvent.blur(baseUrl0, { target: { value: "http://localhost:1234/v1" } });
    await waitFor(() => {
      expect(mockUpdateProviderConfig).toHaveBeenCalledTimes(1);
    });
    expect(mockUpdateProviderConfig).toHaveBeenCalledWith(21, {
      provider: "custom",
      model: "",
      base_url: "http://localhost:1234/v1",
    });
  });

  it("switch-to-custom + chip + natural blur produces exactly ONE full-patch PUT (FIX 2+3)", async () => {
    const user = userEvent.setup();
    mockUpdateProviderConfig.mockClear();
    const providersWithCustom: ProviderOption[] = [
      { key: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", default_model: "deepseek-chat", native: false, models: ["deepseek-chat"] },
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
    ];
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>([
        { id: 22, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "https://api.deepseek.com", api_key: "k", is_primary: true },
      ]);
      return (
        <ProviderConfigList
          llmProviders={providersWithCustom}
          providerConfigs={cfgs}
          onConfigsChange={setCfgs}
        />
      );
    }
    render(<Harness />);

    await user.click(document.getElementById("provider-config-provider-0") as HTMLButtonElement);
    const customOpt = screen.getAllByRole("option").find((o) => /自定义/.test(o.textContent ?? ""));
    await user.click(customOpt!);
    await waitFor(() => {
      expect(screen.getByTestId("provider-config-custom-required-0")).toBeInTheDocument();
    });

    // Chip fills the field — still NO PUT (fill-without-save)
    await user.click(screen.getByRole("button", { name: "LM Studio" }));
    const baseUrl0 = screen.getByTestId("provider-config-baseurl-0") as HTMLInputElement;
    expect(baseUrl0.value).toBe("http://localhost:1234/v1");
    expect(mockUpdateProviderConfig).not.toHaveBeenCalled();

    // Natural blur → exactly ONE PUT carrying the COMPLETE pending patch
    fireEvent.blur(baseUrl0, { target: { value: "http://localhost:1234/v1" } });
    await waitFor(() => {
      expect(mockUpdateProviderConfig).toHaveBeenCalledTimes(1);
    });
    expect(mockUpdateProviderConfig).toHaveBeenCalledWith(22, {
      provider: "custom",
      model: "",
      base_url: "http://localhost:1234/v1",
    });
  });

  it("compat note + blank-base_url hint show for a custom row but NOT a non-custom row (P3)", async () => {
    const user = userEvent.setup();
    const customProviders: ProviderOption[] = [
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
      ...providers,
    ];
    const mixedConfigs: ProviderConfig[] = [
      { id: 5, label: "C", provider: "custom", model: "my-model", base_url: "", api_key: "", is_primary: true },
      { id: 6, label: "A", provider: "deepseek", model: "deepseek-chat", base_url: "", api_key: "k", is_primary: false },
    ];
    render(
      <ProviderConfigList
        llmProviders={customProviders}
        providerConfigs={mixedConfigs}
        onConfigsChange={vi.fn()}
      />
    );
    // Custom row (id 5) is primary → selected by default: compat note + the
    // blank-base_url required hint are both shown in its detail pane.
    expect(screen.getByTestId("provider-config-custom-note-0")).toBeInTheDocument();
    expect(screen.getByTestId("provider-config-custom-required-0")).toBeInTheDocument();

    // Select the NON-custom (deepseek) row → its detail mounts (model field
    // present) but proves the negative: NO compat note, NO required hint —
    // neither for the deepseek row nor lingering from the custom row.
    await user.click(screen.getByTestId("provider-card-row-1"));
    expect(screen.getByTestId("provider-config-model-1")).toBeInTheDocument();
    expect(screen.queryByTestId("provider-config-custom-note-1")).toBeNull();
    expect(screen.queryByTestId("provider-config-custom-required-1")).toBeNull();
    expect(screen.queryByText("settings.customCompatNote")).toBeNull();
    expect(screen.queryByTestId("provider-config-custom-note-0")).toBeNull();
  });

  it("compatibility note renders without the blank hint when base_url is set (P3)", () => {
    const customProviders: ProviderOption[] = [
      { key: "custom", label: "OpenAI-compatible(自定义)", base_url: "", default_model: "", native: false, models: [] },
    ];
    const customConfigs: ProviderConfig[] = [
      { id: 5, label: "C", provider: "custom", model: "my-model", base_url: "http://localhost:1234/v1", api_key: "", is_primary: true },
    ];
    render(
      <ProviderConfigList
        llmProviders={customProviders}
        providerConfigs={customConfigs}
        onConfigsChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("provider-config-custom-note-0")).toBeInTheDocument();
    expect(screen.queryByTestId("provider-config-custom-required-0")).toBeNull();
  });

  it("switching a saved row's provider drops the old provider's verdict (FIX health-reset)", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [cfgs, setCfgs] = useState<ProviderConfig[]>([
        { ...configs[0], last_health: "ok", last_health_at: "2026-08-31T10:00:00" },
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
    expect(screen.getByTestId("provider-status-0")).toHaveAttribute("data-status", "ok");

    // Switch the row's provider deepseek → qwen
    await user.click(document.getElementById("provider-config-provider-0") as HTMLButtonElement);
    const qwenOpt = screen.getAllByRole("option").find((o) => /qwen/i.test(o.textContent ?? ""));
    expect(qwenOpt).toBeTruthy();
    await user.click(qwenOpt!);

    // The stored "ok" was about DeepSeek. Keeping it would vouch for a provider
    // nobody has called — the exact lie this whole surface exists to stop. The
    // backend clears it in update_config; the optimistic row must agree, or the
    // card shows green until something happens to refetch.
    await waitFor(() =>
      expect(screen.getByTestId("provider-status-0")).toHaveAttribute("data-status", "untested"),
    );
  });

  it("a mid-session added config is TESTED for its new id (FIX mid-session-probe)", async () => {
    const user = userEvent.setup();
    mockAddProviderConfig.mockClear();
    mockTestProviderConfig.mockClear();
    mockAddProviderConfig.mockResolvedValueOnce({
      id: 3, label: "C", provider: "deepseek", model: "deepseek-reasoner", base_url: "", api_key: "", is_primary: false,
    });
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
    // The launch-time sweep already ran, so a config added now would sit at
    // "not tested" forever. Test it — which is also the fastest way to tell the
    // user they just typed a bad key.
    await waitFor(() => expect(mockTestProviderConfig).toHaveBeenCalledWith(3));
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

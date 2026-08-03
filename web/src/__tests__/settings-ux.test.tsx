/**
 * Task UX3 — Settings reflow: strategy gating, Test button, DOM ordering.
 *
 * TDD: these tests are written first and drive the implementation.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
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

vi.mock("../stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: null }) },
}));

// ── api mock ───────────────────────────────────────────────────────────────────
const mockTestLlm = vi.fn();
const mockTestProviderConfig = vi.fn();
const mockGetCatalog = vi.fn();
const mockAddProviderConfig = vi.fn();
const mockUpdateProviderConfig = vi.fn();
const mockDeleteProviderConfig = vi.fn();
const mockSuggestPrimary = vi.fn();
const mockSetPrimaryProviderConfig = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    updateSettings: vi.fn().mockResolvedValue({}),
  },
  API_BASE: "",
  addProviderConfig: (...args: unknown[]) => mockAddProviderConfig(...args),
  updateProviderConfig: (...args: unknown[]) => mockUpdateProviderConfig(...args),
  setPrimaryProviderConfig: (...args: unknown[]) => mockSetPrimaryProviderConfig(...args),
  deleteProviderConfig: (...args: unknown[]) => mockDeleteProviderConfig(...args),
  suggestPrimary: (...args: unknown[]) => mockSuggestPrimary(...args),
  getCatalog: (...args: unknown[]) => mockGetCatalog(...args),
  testLlm: (...args: unknown[]) => mockTestLlm(...args),
  testProviderConfig: (...args: unknown[]) => mockTestProviderConfig(...args),
  probeProviderHealth: vi.fn().mockResolvedValue({
    state: "reachable_models", latency_ms: 1, detail: null, last_health_at: "2026-07-12T00:00:00",
  }),
}));

import ProviderConfigList from "../components/ProviderConfigList";
import type { ProviderOption, ProviderConfig } from "../api/client.types";

const providers: ProviderOption[] = [
  {
    key: "deepseek",
    label: "DeepSeek",
    base_url: "",
    default_model: "deepseek-chat",
    native: false,
    models: ["deepseek-chat", "deepseek-reasoner"],
  },
  {
    key: "qwen",
    label: "Qwen",
    base_url: "",
    default_model: "qwen-max",
    native: false,
    models: ["qwen-max", "qwen-plus"],
  },
];

const twoConfigs: ProviderConfig[] = [
  {
    id: 1,
    label: "A",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "",
    api_key: "de...cd",
    is_primary: true,
  },
  {
    id: 2,
    label: "B",
    provider: "qwen",
    model: "qwen-max",
    base_url: "",
    api_key: "qw...ef",
    is_primary: false,
  },
];

const oneConfig: ProviderConfig[] = [twoConfigs[0]];

beforeEach(() => {
  vi.clearAllMocks();
  mockGetCatalog.mockResolvedValue([]);
  mockSuggestPrimary.mockResolvedValue(null);
  mockAddProviderConfig.mockResolvedValue({
    id: 3,
    label: "C",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "",
    api_key: "",
    is_primary: false,
  });
  mockUpdateProviderConfig.mockResolvedValue({});
  mockDeleteProviderConfig.mockResolvedValue({ ok: true });
  mockSetPrimaryProviderConfig.mockResolvedValue({ ok: true });
});

// ── (C) Strategy renders in the RoutingStrategyCard at the TOP of the section ──
// Task 3.3 lifted the strategy Select + Suggest-primary into RoutingStrategyCard
// placed ABOVE the master-detail, so the strategy control now PRECEDES the
// add-model button (which lives at the bottom of the master list).

describe("(C) Strategy control position", () => {
  it("strategy control appears AFTER the models — it is the question you answer once there is more than one", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    const strategyEl = document.getElementById("provider-strategy-select");
    expect(strategyEl).not.toBeNull();

    // Get add button
    const addBtn = screen.getByRole("button", { name: /btnAddModel/i });

    // Inverted deliberately in v0.1.18: routing strategy now sits BELOW the
    // model configuration. It is the question you answer once you have more
    // than one model, and having it first pushed down the thing everyone comes
    // to this page for. FOLLOWING = strategyEl comes after addBtn.
    const position = addBtn.compareDocumentPosition(strategyEl!);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

// ── (D) Strategy gating ───────────────────────────────────────────────────────

describe("(D) Strategy gating by config count", () => {
  it("with 1 config: non-single options are aria-disabled when panel is open", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={oneConfig}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    // Open the strategy Select
    const trigger = document.getElementById("provider-strategy-select") as HTMLButtonElement;
    expect(trigger).not.toBeNull();
    await user.click(trigger);

    // All three non-single options should be aria-disabled
    const allOptions = screen.getAllByRole("option");
    // Filter by text content matching i18n keys
    const costOption = allOptions.find((o) => /strategyOptions\.cost/i.test(o.textContent ?? ""));
    const balancedOption = allOptions.find((o) => /strategyOptions\.balanced/i.test(o.textContent ?? ""));
    const perfOption = allOptions.find((o) => /strategyOptions\.performance/i.test(o.textContent ?? ""));

    expect(costOption).toBeTruthy();
    expect(balancedOption).toBeTruthy();
    expect(perfOption).toBeTruthy();

    expect(costOption).toHaveAttribute("aria-disabled", "true");
    expect(balancedOption).toHaveAttribute("aria-disabled", "true");
    expect(perfOption).toHaveAttribute("aria-disabled", "true");
  });

  it("with 1 config: single option is NOT aria-disabled", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={oneConfig}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    const trigger = document.getElementById("provider-strategy-select") as HTMLButtonElement;
    await user.click(trigger);

    const allOptions = screen.getAllByRole("option");
    const singleOption = allOptions.find((o) => /strategyOptions\.single/i.test(o.textContent ?? ""));
    expect(singleOption).toBeTruthy();
    expect(singleOption).not.toHaveAttribute("aria-disabled", "true");
  });

  it("with 2+ configs: all strategy options are enabled", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    const trigger = document.getElementById("provider-strategy-select") as HTMLButtonElement;
    await user.click(trigger);

    const allOptions = screen.getAllByRole("option");
    const costOption = allOptions.find((o) => /strategyOptions\.cost/i.test(o.textContent ?? ""));
    const balancedOption = allOptions.find((o) => /strategyOptions\.balanced/i.test(o.textContent ?? ""));
    const perfOption = allOptions.find((o) => /strategyOptions\.performance/i.test(o.textContent ?? ""));

    expect(costOption).toBeTruthy();
    expect(balancedOption).toBeTruthy();
    expect(perfOption).toBeTruthy();

    expect(costOption).not.toHaveAttribute("aria-disabled", "true");
    expect(balancedOption).not.toHaveAttribute("aria-disabled", "true");
    expect(perfOption).not.toHaveAttribute("aria-disabled", "true");
  });

  it("with 1 config: shows hint text about needing 2+ models", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={oneConfig}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    expect(
      screen.getByText("settings.strategyHint")
    ).toBeInTheDocument();
  });

  it("with 2+ configs: hint text is NOT shown", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="balanced"
        onStrategyChange={vi.fn()}
      />
    );

    expect(
      screen.queryByText("settings.strategyHint")
    ).toBeNull();
  });
});

// ── (E) "Test all" batch button ───────────────────────────────────────────────

describe("(E) Test all batch button", () => {
  it("shows a single 'Test all' button when there are saved configs", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    expect(screen.getByTestId("provider-test-all")).toBeInTheDocument();
  });

  it("does NOT show per-row Test buttons on saved rows", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    expect(screen.queryByTestId("provider-config-test-0")).toBeNull();
    expect(screen.queryByTestId("provider-config-test-1")).toBeNull();
  });

  it("clicking Test all calls testProviderConfig for each config and shows ok indicators", async () => {
    mockTestProviderConfig.mockResolvedValue({ ok: true, latency_ms: 200 });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    const testAllBtn = screen.getByTestId("provider-test-all");
    fireEvent.click(testAllBtn);

    await waitFor(() => {
      expect(mockTestProviderConfig).toHaveBeenCalledWith(1);
      expect(mockTestProviderConfig).toHaveBeenCalledWith(2);
    });

    await waitFor(() => {
      // Both rows should show the ok indicator
      const okIndicators = screen.getAllByText("settings.testOk");
      expect(okIndicators.length).toBe(2);
    });
  });

  it("shows failure indicators for failed tests after Test all", async () => {
    mockTestProviderConfig.mockResolvedValueOnce({ ok: false, error: "Invalid API key" });
    mockTestProviderConfig.mockResolvedValueOnce({ ok: true, latency_ms: 100 });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId("provider-test-all"));

    await waitFor(() => {
      // The failed config is the selected one, so its error shows in BOTH the
      // master-list row and the detail-pane ConnectionTester (level-2 result).
      expect(screen.getAllByText(/Invalid API key/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("settings.testOk")).toBeInTheDocument();
    });
  });
});

// ── (F) Deep test surfaces the latency from testProviderConfig ───────────────

describe("(F) Deep test latency wiring", () => {
  it("clicking the detail-pane deep test shows the latency_ms from testProviderConfig", async () => {
    mockTestProviderConfig.mockResolvedValue({ ok: true, latency_ms: 150 });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    // The primary config (id 1) is selected by default → its ConnectionTester
    // level-2 button drives the deep test.
    fireEvent.click(screen.getByTestId("connection-test-level2"));

    await waitFor(() => {
      expect(mockTestProviderConfig).toHaveBeenCalledWith(1);
      expect(screen.getByText(/· 150ms/)).toBeInTheDocument();
    });
  });
});

// ── (E) Draft / add-new flow: Add enabled when fields filled (no test gate) ──

describe("(E) Draft config: Add enabled when fields are filled", () => {
  it("Add button is enabled with an empty api_key (P3 FIX 1: keyless local servers)", async () => {
    // D3/B3: api_key is OPTIONAL — keyless configs (ollama, LM Studio, vLLM)
    // are legitimate and the draft is their only UI entry point. The backend
    // accepts empty keys everywhere (empty key = no Authorization header).
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    // Open draft form — provider + model are pre-filled from defaults
    fireEvent.click(screen.getByRole("button", { name: /btnAddModel/i }));

    // Confirm must NOT be gated on the (empty) api_key
    await waitFor(() => {
      expect(screen.getByTestId("provider-draft-confirm")).not.toBeDisabled();
    });
  });

  it("Add button is enabled once provider + model + api_key are non-empty (no test required)", async () => {
    const user = userEvent.setup();
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    // Open draft form
    fireEvent.click(screen.getByRole("button", { name: /btnAddModel/i }));

    // Type an api_key — provider+model are pre-filled from defaults
    const keyInput = await screen.findByPlaceholderText("settings.labelConfigApiKey");
    await user.type(keyInput, "sk-test-key");

    // Confirm button should now be enabled WITHOUT needing to test first
    await waitFor(() => {
      expect(screen.getByTestId("provider-draft-confirm")).not.toBeDisabled();
    });
  });

  it("does NOT render a per-draft Test button", async () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /btnAddModel/i }));

    await waitFor(() => {
      expect(screen.queryByTestId("provider-draft-test")).toBeNull();
    });
  });
});

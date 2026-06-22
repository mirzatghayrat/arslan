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

// ── (C) Strategy renders AFTER config rows in the DOM ────────────────────────

describe("(C) Strategy control position", () => {
  it("strategy control appears AFTER the add-model button in the DOM", () => {
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

    // Strategy control should come AFTER the add-model button in DOM order
    // Node.DOCUMENT_POSITION_FOLLOWING = 4 means strategyEl is after addBtn
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

// ── (E) Per-config Test button ────────────────────────────────────────────────

describe("(E) Per-config Test button on saved rows", () => {
  it("each saved config row shows a Test button", () => {
    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    // Each row gets a data-testid="provider-config-test-{idx}"
    const testBtn0 = screen.getByTestId("provider-config-test-0");
    const testBtn1 = screen.getByTestId("provider-config-test-1");
    expect(testBtn0).toBeInTheDocument();
    expect(testBtn1).toBeInTheDocument();
  });

  it("Test button calls testProviderConfig with config id", async () => {
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

    const testBtn0 = screen.getByTestId("provider-config-test-0");
    fireEvent.click(testBtn0);

    await waitFor(() => {
      expect(mockTestProviderConfig).toHaveBeenCalledWith(1);
    });
  });

  it("shows success status after successful test", async () => {
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

    const testBtn0 = screen.getByTestId("provider-config-test-0");
    fireEvent.click(testBtn0);

    await waitFor(() => {
      expect(screen.getByText("settings.testOk")).toBeInTheDocument();
    });
  });

  it("shows failure status after failed test", async () => {
    mockTestProviderConfig.mockResolvedValue({ ok: false, error: "Invalid API key" });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={twoConfigs}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    const testBtn0 = screen.getByTestId("provider-config-test-0");
    fireEvent.click(testBtn0);

    await waitFor(() => {
      expect(screen.getByText(/Invalid API key/)).toBeInTheDocument();
    });
  });
});

// ── (E) Draft / add-new flow: Add gated until Test passes ────────────────────

describe("(E) Draft config: Add gated until successful test", () => {
  it("Add button is disabled until Test passes for a new draft row", async () => {
    mockTestLlm.mockResolvedValue({ ok: true, latency_ms: 100 });
    mockAddProviderConfig.mockResolvedValue({
      id: 10,
      label: "New",
      provider: "deepseek",
      model: "deepseek-chat",
      base_url: "",
      api_key: "",
      is_primary: false,
    });

    render(
      <ProviderConfigList
        llmProviders={providers}
        providerConfigs={[]}
        onConfigsChange={vi.fn()}
        strategy="single"
        onStrategyChange={vi.fn()}
      />
    );

    // Click "Add model" to open the draft form
    const addBtn = screen.getByRole("button", { name: /btnAddModel/i });
    fireEvent.click(addBtn);

    // The confirm button in the draft form should be disabled initially
    await waitFor(() => {
      const confirmBtn = screen.getByTestId("provider-draft-confirm");
      expect(confirmBtn).toBeDisabled();
    });

    // Click Test in the draft
    const testBtn = screen.getByTestId("provider-draft-test");
    fireEvent.click(testBtn);

    // After successful test, Add/confirm should be enabled
    await waitFor(() => {
      const confirmBtn = screen.getByTestId("provider-draft-confirm");
      expect(confirmBtn).not.toBeDisabled();
    });
  });
});
